"""Orquesta el pipeline de extracción de boletas sobre una carpeta completa.

Uso:
    python src/main.py boletas/ --output output/Expense_Report.xlsx

Una vez leídas todas las boletas y antes de escribir el Excel final, pide por
consola el FX de cada moneda no-CLP presente en el reporte, y una descripción
para el nombre del archivo — que siempre queda como
"Expense_Report_<descripción saneada>.xlsx" en el directorio de `--output`,
reemplazando el nombre de archivo indicado (no el directorio).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import api_key
import audit_writer
import cost
import currency
import excel_writer
import preprocess
import validate
from excel_writer import ExpenseRow
from extract import ExtractionResult, extract_receipt

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".pdf"}

_MONTH_ABBR = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def load_config(config_path: Path) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _coerce_amount(raw_amount) -> Optional[Decimal]:
    if raw_amount is None:
        return None
    if isinstance(raw_amount, (int, float, Decimal)):
        return Decimal(str(raw_amount))
    try:
        return currency.parse_localized_amount(str(raw_amount))
    except currency.CurrencyParseError:
        return None


def _coerce_date(raw_date: Optional[str]) -> Optional[date_cls]:
    if not raw_date:
        return None
    try:
        return date_cls.fromisoformat(raw_date)
    except ValueError:
        return None


def _format_date_like_excel(d: date_cls) -> str:
    # Mismo formato que la columna Date de la plantilla ([$-409]d\-mmm\-yy;@),
    # ej. 27-May-26. Se usan abreviaturas en inglés fijas (no locale del sistema)
    # porque ese formato de Excel está fijado a en-US independiente de la máquina.
    return f"{d.day}-{_MONTH_ABBR[d.month - 1]}-{d.year % 100:02d}"


def build_comments(filename: str) -> str:
    # El nombre de archivo es la descripción de la rendición; sin extensión y sin
    # fecha (Path.stem remueve solo la última extensión: "a.b.jpg" -> "a.b").
    return Path(filename).stem


REVIEW_COMMENTS_TEXT = "Boleta para revisión, mirar auditoría"


def _build_expense_row(
    file_path: Path, result: ExtractionResult, validation: "validate.ValidationResult"
) -> Optional[ExpenseRow]:
    """Arma la fila a escribir en el Excel, o None si no se determinó el monto.

    Se escribe la fila con los valores que sí se pudieron extraer aunque la boleta
    haya quedado marcada para revisión (la marca se mantiene en el audit report;
    esto no la elimina). En ese caso Comments avisa que hay que mirar la auditoría,
    en vez del nombre de archivo + fecha que llevan las filas OK.
    """
    if result.amount is None:
        return None

    coerced_date = _coerce_date(result.date)
    if validation.ok:
        comments = build_comments(file_path.name)
    else:
        comments = REVIEW_COMMENTS_TEXT

    return ExpenseRow(
        date=coerced_date,
        amount=result.amount,
        currency=result.currency,
        expense_type=result.expense_type,
        source_file=file_path.name,
        comments=comments,
    )


_FORBIDDEN_FILENAME_CHARS_RE = re.compile(r'[\/\\:*?"<>|]')


def sanitize_filename_component(text: str) -> str:
    """Sanea texto para usarlo como parte de un nombre de archivo: reemplaza los
    caracteres prohibidos (/ \\ : * ? " < > |) y los espacios (internos o de los
    extremos) por guion bajo, colapsando repeticiones."""
    text = _FORBIDDEN_FILENAME_CHARS_RE.sub("_", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def prompt_report_description() -> str:
    """Pide al usuario una descripción para el nombre del archivo de salida."""
    while True:
        raw = input("Descripción del reporte (para el nombre del archivo): ")
        sanitized = sanitize_filename_component(raw)
        if sanitized:
            return sanitized
        print("La descripción queda vacía después de sanearla. Intenta de nuevo.")


def _parse_positive_fx(raw: str) -> Optional[float]:
    try:
        value = currency.parse_localized_amount(raw)
    except currency.CurrencyParseError:
        return None
    if value <= 0:
        return None
    return float(value)


def prompt_fx_rates(currencies: Set[str]) -> Dict[str, float]:
    """Pide al usuario el valor de FX (-> CLP) para cada moneda distinta a CLP en
    `currencies`. CLP no se pregunta (su FX siempre es 1, ver excel_writer.DEFAULT_FX)."""
    fx_rates: Dict[str, float] = {}
    for code in sorted(c for c in currencies if c and c != "CLP"):
        while True:
            raw = input(f"Tipo de cambio (FX) para {code} -> CLP: ")
            value = _parse_positive_fx(raw)
            if value is not None:
                fx_rates[code] = value
                break
            print("Valor inválido. Ingresa un número positivo (ej. 922 o 922,50).")
    return fx_rates


def process_file(file_path: Path, config: dict) -> tuple[ExtractionResult, validate.ValidationResult]:
    pages = preprocess.preprocess_file(file_path, config)
    result = extract_receipt(pages, config)

    amount = _coerce_amount(result.amount)
    if amount is not None:
        result.amount = amount
    normalized_currency = currency.normalize_currency_code(
        result.currency, config.get("extraction", {}).get("currencies", currency.ALLOWED_CURRENCIES)
    )
    result.currency = normalized_currency

    validation = validate.validate_extraction(result, config)
    return result, validation


def run(input_dir: Path, config: dict, output_path: Path, audit_path: Path) -> None:
    files = sorted(
        p for p in input_dir.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not files:
        print(f"No se encontraron boletas soportadas en {input_dir}")
        return

    rows_to_write: List[ExpenseRow] = []
    review_cases: List[audit_writer.ReviewCase] = []
    total_usage = cost.TokenUsage()
    n_ok = 0

    for file_path in files:
        print(f"Procesando {file_path.name}...")
        result, validation = process_file(file_path, config)
        total_usage.add(result.usage)

        if validation.ok:
            n_ok += 1
        else:
            review_cases.append((file_path, result, validation))

        row = _build_expense_row(file_path, result, validation)
        if row is not None:
            rows_to_write.append(row)

    rows_to_write.sort(key=lambda r: (r.date or date_cls.max, r.source_file))

    currencies_present = {row.currency for row in rows_to_write if row.currency}
    fx_rates = prompt_fx_rates(currencies_present)
    for row in rows_to_write:
        row.fx = fx_rates.get(row.currency, excel_writer.DEFAULT_FX)

    description = prompt_report_description()
    output_path = output_path.with_name(f"Expense_Report_{description}.xlsx")

    excel_writer.write_expense_report(rows_to_write, config, output_path)
    audit_result_path = audit_writer.write_audit_report(review_cases, config, audit_path)

    print()
    print(f"Excel de rendición: {output_path}")
    if audit_result_path is not None:
        print(f"Reporte de auditoría: {audit_result_path}")
    else:
        print("Reporte de auditoría: sin casos para revisión, no se generó archivo")
    print(f"Resumen: {n_ok} OK, {len(review_cases)} para revisión, {len(files)} total")
    print()
    print(cost.format_summary(len(files), total_usage, config.get("pricing", {})))


def _ensure_utf8_console() -> None:
    """Fuerza UTF-8 en stdout/stderr. Sin esto, en una consola Windows con code
    page legacy (cp1252/cp437) los textos con tildes, "──" o "$" del resumen
    pueden lanzar UnicodeEncodeError."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def main() -> None:
    _ensure_utf8_console()

    parser = argparse.ArgumentParser(description="Procesa una carpeta de boletas de viaje.")
    parser.add_argument("input_dir", type=Path, help="Carpeta con boletas (jpg/png/pdf)")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--audit", type=Path, default=None)
    parser.add_argument(
        "--secrets",
        type=Path,
        default=api_key.DEFAULT_SECRETS_PATH,
        help="Archivo de secretos local con la API key de Anthropic",
    )
    args = parser.parse_args()

    api_key.resolve_api_key(args.secrets)

    config = load_config(args.config)
    output_path = args.output or Path(config["output"]["default_excel_output_path"])
    audit_path = args.audit or Path(config["output"]["audit_report_path"])

    run(args.input_dir, config, output_path, audit_path)


if __name__ == "__main__":
    main()
