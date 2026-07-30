from datetime import date
from pathlib import Path

import openpyxl

import main
import preprocess
from extract import ExtractionResult
from main import REVIEW_COMMENTS_TEXT, _build_expense_row, _format_date_like_excel, build_comments
from validate import ValidationResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = (
    PROJECT_ROOT / "plantilla" / "Form - Chile Expense Report - Peru Travel Junio 2026.xlsx"
)

BASE_CONFIG = {
    "excel": {
        "template_path": str(TEMPLATE_PATH),
        "sheet_name": "Expense Report",
        "first_data_row": 9,
        "last_data_row": 32,
    },
    "extraction": {"currencies": ["CLP", "USD", "BRL", "ARG", "PEN", "COP", "EUR"]},
    "validation": {
        "min_field_confidence": 0.6,
        "min_overall_confidence": 0.6,
        "amount_consistency_tolerance": 1.0,
    },
    "pricing": {
        "usd_per_million": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30}
    },
}


def test_format_date_like_excel_matches_date_column_format():
    # Mismo formato que la columna Date de la plantilla ([$-409]d\-mmm\-yy;@).
    assert _format_date_like_excel(date(2026, 5, 27)) == "27-May-26"


def test_format_date_like_excel_does_not_zero_pad_day():
    # El código de formato de Excel usa "d" (sin ceros a la izquierda), no "dd".
    assert _format_date_like_excel(date(2026, 6, 7)) == "7-Jun-26"


def test_build_comments_with_date():
    result = build_comments("Taxi from Home to SCL Airport Invoice.jpg", "7-Jun-26")
    assert result == "Taxi from Home to SCL Airport Invoice.jpg en la fecha 7-Jun-26"


def test_build_comments_without_date():
    # Sin fecha extraíble: solo el nombre de archivo, sin sufijo.
    result = build_comments("Taxi to Kyndryl.pdf", None)
    assert result == "Taxi to Kyndryl.pdf"


def test_run_prints_execution_summary_with_accumulated_usage(tmp_path, monkeypatch, capsys):
    # No golpea la red: mockea preprocess.preprocess_file y extract_receipt para
    # simular dos boletas procesadas, cada una con su propio usage de la API.
    input_dir = tmp_path / "boletas"
    input_dir.mkdir()
    (input_dir / "a.jpg").write_bytes(b"fake")
    (input_dir / "b.jpg").write_bytes(b"fake")

    usages = iter(
        [
            {"input_tokens": 1000, "output_tokens": 150},
            {"input_tokens": 500, "output_tokens": 50, "cache_read_input_tokens": 200},
        ]
    )

    def fake_preprocess_file(file_path, config):
        return ["fake-page"]

    def fake_extract_receipt(pages, config):
        return ExtractionResult(
            date="2026-06-12",
            currency="PEN",
            amount=100.0,
            expense_type="Taxi",
            confidence={
                "overall": 0.95,
                "amount": 0.95,
                "currency": 0.95,
                "date": 0.95,
                "expense_type": 0.95,
            },
            usage=next(usages),
        )

    monkeypatch.setattr(preprocess, "preprocess_file", fake_preprocess_file)
    monkeypatch.setattr(main, "extract_receipt", fake_extract_receipt)

    config = {
        "excel": {
            "template_path": str(TEMPLATE_PATH),
            "sheet_name": "Expense Report",
            "first_data_row": 9,
            "last_data_row": 32,
        },
        "extraction": {"currencies": ["CLP", "USD", "BRL", "ARG", "PEN", "COP", "EUR"]},
        "validation": {
            "min_field_confidence": 0.6,
            "min_overall_confidence": 0.6,
            "amount_consistency_tolerance": 1.0,
        },
        "pricing": {
            "usd_per_million": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30}
        },
    }

    main.run(input_dir, config, tmp_path / "out.xlsx", tmp_path / "audit.csv")

    out = capsys.readouterr().out
    assert "── Resumen de ejecución ──" in out
    assert "Boletas procesadas:    2" in out
    assert "Tokens de entrada:     1,500" in out  # 1000 + 500, acumulado entre las dos boletas
    assert "Tokens de salida:      200" in out  # 150 + 50
    assert "Costo estimado (USD):" in out
    assert "estimado" in out.lower()


# --- _build_expense_row: filas para revisión con monto sí se escriben ---


def _make_ok_result(**overrides) -> ExtractionResult:
    defaults = dict(
        date="2026-06-12",
        currency="PEN",
        amount=100.0,
        expense_type="Taxi",
        confidence={
            "overall": 0.95,
            "amount": 0.95,
            "currency": 0.95,
            "date": 0.95,
            "expense_type": 0.95,
        },
    )
    defaults.update(overrides)
    return ExtractionResult(**defaults)


def test_build_expense_row_review_with_amount_writes_row_with_review_comments():
    # Boleta marcada para revisión (ej. moneda no determinada) pero con monto sí
    # determinado: la fila se escribe, con Comments fijo avisando revisar la auditoría.
    result = _make_ok_result(currency=None)
    validation = ValidationResult(status="REVIEW", reasons=["no se pudo determinar la moneda"])

    row = _build_expense_row(Path("boleta.jpg"), result, validation)

    assert row is not None
    assert row.amount == 100.0
    assert row.currency is None
    assert row.comments == REVIEW_COMMENTS_TEXT == "Boleta para revisión, mirar auditoría"


def test_build_expense_row_ok_keeps_filename_date_comments():
    result = _make_ok_result()
    validation = ValidationResult(status="OK", reasons=[])

    row = _build_expense_row(Path("Taxi to Kyndryl.pdf"), result, validation)

    assert row is not None
    assert row.comments == "Taxi to Kyndryl.pdf en la fecha 12-Jun-26"


def test_build_expense_row_review_without_amount_returns_none():
    # Sin monto determinado: comportamiento actual sin cambios, no se escribe fila.
    result = _make_ok_result(amount=None)
    validation = ValidationResult(status="REVIEW", reasons=["no se pudo determinar el monto"])

    row = _build_expense_row(Path("boleta.jpg"), result, validation)

    assert row is None


def test_run_writes_review_rows_with_amount_and_keeps_review_marking(tmp_path, monkeypatch, capsys):
    # Tres boletas: una OK, una para revisión CON monto (debe escribirse con el
    # comment fijo), una para revisión SIN monto (no debe escribirse, como hoy).
    input_dir = tmp_path / "boletas"
    input_dir.mkdir()
    (input_dir / "ok.jpg").write_bytes(b"fake")
    (input_dir / "review_with_amount.jpg").write_bytes(b"fake")
    (input_dir / "review_without_amount.jpg").write_bytes(b"fake")

    results_by_file = {
        "ok.jpg": _make_ok_result(),
        # Moneda no reconocida -> REVIEW, pero el monto sí se determinó.
        "review_with_amount.jpg": _make_ok_result(currency=None, amount=250.0),
        # Sin monto -> REVIEW y sin dato para escribir la fila.
        "review_without_amount.jpg": _make_ok_result(amount=None),
    }

    # Reemplaza process_file completo (evita depender de preprocess/extract_receipt):
    # dado el archivo, devuelve el ExtractionResult fijado arriba y su validación real.
    def fake_process_file(file_path, config):
        result = results_by_file[file_path.name]
        validation = main.validate.validate_extraction(result, config)
        return result, validation

    monkeypatch.setattr(main, "process_file", fake_process_file)

    output_path = tmp_path / "out.xlsx"
    audit_path = tmp_path / "audit.csv"
    main.run(input_dir, BASE_CONFIG, output_path, audit_path)

    out = capsys.readouterr().out
    # (d) la marca de revisión sigue apareciendo en el resumen impreso.
    assert "Resumen: 1 OK, 2 para revisión, 3 total" in out

    wb = openpyxl.load_workbook(output_path)
    ws = wb["Expense Report"]

    written_comments = [
        ws.cell(row=r, column=9).value for r in range(9, 11) if ws.cell(row=r, column=9).value
    ]
    # Solo 2 filas escritas: la OK y la de revisión CON monto (no la de revisión sin monto).
    assert len(written_comments) == 2
    assert REVIEW_COMMENTS_TEXT in written_comments
    assert any(c.startswith("ok.jpg en la fecha") for c in written_comments)
    assert not any("review_without_amount" in c for c in written_comments)

    with open(audit_path, newline="", encoding="utf-8") as f:
        import csv as csv_module

        audit_rows = list(csv_module.DictReader(f))
    statuses = {row["source_file"]: row["status"] for row in audit_rows}
    assert statuses == {
        "ok.jpg": "OK",
        "review_with_amount.jpg": "REVIEW",
        "review_without_amount.jpg": "REVIEW",
    }
