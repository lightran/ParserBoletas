from datetime import date
from pathlib import Path

import main
import preprocess
from extract import ExtractionResult
from main import _format_date_like_excel, build_comments

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = (
    PROJECT_ROOT / "plantilla" / "Form - Chile Expense Report - Peru Travel Junio 2026.xlsx"
)


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
