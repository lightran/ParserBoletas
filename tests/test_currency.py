from decimal import Decimal

import pytest

import currency


# Casos sacados directamente de las 12 boletas reales en boletas/ y de la
# plantilla de rendición ya resuelta.
REAL_RECEIPT_AMOUNTS = [
    ("$ 464.717", Decimal("464717")),           # Airline Ticket Invoice.pdf (CLP, sin decimales)
    ("$464.717", Decimal("464717")),
    ("$ 33.200", Decimal("33200")),              # Taxi Transvip (CLP)
    ("$ 28.000", Decimal("28000")),
    ("990.00", Decimal("990.00")),                # Hotel Invoice 6 Nights.pdf (USD)
    ("IMPORTE TOTAL 270.92", Decimal("270.92")),  # Hotel Services invoice.pdf (USD)
    ("S/ 235.40", Decimal("235.40")),             # Voucher izipay (PEN)
    ("S/ 324.04", Decimal("324.04")),
    ("S/ 223.50", Decimal("223.50")),
    ("S/. 214.00", Decimal("214.00")),
    ("23.90", Decimal("23.90")),
    ("20.47", Decimal("20.47")),
]


@pytest.mark.parametrize("raw,expected", REAL_RECEIPT_AMOUNTS)
def test_parse_localized_amount_real_receipts(raw, expected):
    assert currency.parse_localized_amount(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.234,56", Decimal("1234.56")),   # formato europeo/brasileño: coma decimal
        ("1,234.56", Decimal("1234.56")),   # formato anglo: punto decimal
        ("1.234.567", Decimal("1234567")),  # miles con puntos, sin decimales
        ("1,234,567", Decimal("1234567")),  # miles con comas, sin decimales
        ("-45.00", Decimal("-45.00")),
        ("1234", Decimal("1234")),
        ("1234.5", Decimal("1234.5")),
    ],
)
def test_parse_localized_amount_synthetic_formats(raw, expected):
    assert currency.parse_localized_amount(raw) == expected


def test_parse_localized_amount_raises_on_garbage():
    with pytest.raises(currency.CurrencyParseError):
        currency.parse_localized_amount("no hay numero aqui")


def test_parse_localized_amount_raises_on_none():
    with pytest.raises(currency.CurrencyParseError):
        currency.parse_localized_amount(None)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("CLP", "CLP"),
        ("clp", "CLP"),
        ("ARS", "ARG"),  # la plantilla usa ARG, no el código ISO ARS
        ("ARG", "ARG"),
        ("S/", "PEN"),
        ("S/.", "PEN"),
        ("SOLES", "PEN"),
        ("US$", "USD"),
        ("USD", "USD"),
        ("DÓLARES AMERICANOS", "USD"),
        ("R$", "BRL"),
        ("REALES", "BRL"),
        ("€", "EUR"),
        ("EUROS", "EUR"),
        ("COL$", "COP"),
        ("XYZ", None),
        ("", None),
    ],
)
def test_normalize_currency_code(raw, expected):
    assert currency.normalize_currency_code(raw) == expected
