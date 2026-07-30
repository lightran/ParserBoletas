"""Orquesta el pipeline de extracción de boletas sobre una carpeta completa.

Uso:
    python src/main.py boletas/ --output output/Expense_Report.xlsx
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date as date_cls
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

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


def build_comments(filename: str, date_str: Optional[str]) -> str:
    if date_str:
        return f"{filename} en la fecha {date_str}"
    return filename


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

    ok_rows: List[ExpenseRow] = []
    audit_entries = []

    for file_path in files:
        print(f"Procesando {file_path.name}...")
        result, validation = process_file(file_path, config)

        audit_entries.append(
            {
                "source_file": file_path.name,
                "vendor": result.vendor,
                "date": result.date,
                "currency": result.currency,
                "amount": result.amount,
                "expense_type": result.expense_type,
                "status": validation.status,
                "confidence_overall": result.overall_confidence(),
                "reasons": "; ".join(validation.reasons),
                "notes": result.notes,
            }
        )

        if validation.ok:
            coerced_date = _coerce_date(result.date)
            formatted_date = _format_date_like_excel(coerced_date) if coerced_date else None
            comments = build_comments(file_path.name, formatted_date)
            ok_rows.append(
                ExpenseRow(
                    date=coerced_date,
                    amount=result.amount,
                    currency=result.currency,
                    expense_type=result.expense_type,
                    source_file=file_path.name,
                    comments=comments,
                )
            )

    ok_rows.sort(key=lambda r: (r.date or date_cls.max, r.source_file))

    excel_writer.write_expense_report(ok_rows, config, output_path)
    _write_audit_report(audit_entries, audit_path)

    n_ok = sum(1 for e in audit_entries if e["status"] == "OK")
    n_review = len(audit_entries) - n_ok
    print()
    print(f"Excel de rendición: {output_path}")
    print(f"Reporte de auditoría: {audit_path}")
    print(f"Resumen: {n_ok} OK, {n_review} para revisión, {len(audit_entries)} total")


def _write_audit_report(entries: list[dict], audit_path: Path) -> None:
    audit_path = Path(audit_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_file",
        "vendor",
        "date",
        "currency",
        "amount",
        "expense_type",
        "status",
        "confidence_overall",
        "reasons",
        "notes",
    ]
    with open(audit_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description="Procesa una carpeta de boletas de viaje.")
    parser.add_argument("input_dir", type=Path, help="Carpeta con boletas (jpg/png/pdf)")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--audit", type=Path, default=None)
    args = parser.parse_args()

    config = load_config(args.config)
    output_path = args.output or Path(config["output"]["default_excel_output_path"])
    audit_path = args.audit or Path(config["output"]["audit_report_path"])

    run(args.input_dir, config, output_path, audit_path)


if __name__ == "__main__":
    main()
