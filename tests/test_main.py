from datetime import date

from main import _format_date_like_excel, build_comments


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
