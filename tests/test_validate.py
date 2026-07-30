import currency
from extract import ExtractionResult
from validate import check_amount_consistency, validate_extraction

CONFIG = {
    "validation": {
        "min_field_confidence": 0.6,
        "min_overall_confidence": 0.6,
        "amount_consistency_tolerance": 1.0,
    },
    "extraction": {
        "currencies": ["CLP", "USD", "BRL", "ARG", "PEN", "COP", "EUR"],
    },
}

HIGH_CONF = {
    "vendor": 0.95,
    "date": 0.95,
    "currency": 0.95,
    "amount": 0.95,
    "expense_type": 0.95,
    "overall": 0.95,
}


def make_result(**overrides) -> ExtractionResult:
    defaults = dict(
        vendor="Test SAC",
        date="2026-06-12",
        currency="PEN",
        amount=223.50,
        net_amount=None,
        tax_amount=None,
        tip_amount=None,
        expense_type="Travel - Meals",
        confidence=dict(HIGH_CONF),
    )
    defaults.update(overrides)
    return ExtractionResult(**defaults)


# --- Consistencia neto + impuesto (+ propina) ≈ total, con montos reales ---


def test_consistency_lunch_america_movil_with_tip():
    # Boleta S/214.00 + propina S/21.40 (voucher izipay) = S/235.40
    assert check_amount_consistency(214.00, 0, 21.40, 235.40, tolerance=1.0)


def test_consistency_lunch_jun12_with_tip():
    # Boleta S/203.20 + propina S/20.30 (voucher niubiz) = S/223.50
    assert check_amount_consistency(203.20, 0, 20.30, 223.50, tolerance=1.0)


def test_consistency_hotel_services_no_voucher():
    # Factura ya viene con el total final, neto+IGV+propina = importe total
    assert check_amount_consistency(194.03, 34.92, 22.57, 251.52, tolerance=0.5)


def test_consistency_fails_when_amounts_dont_add_up():
    assert not check_amount_consistency(100, 10, 0, 200, tolerance=1.0)


def test_consistency_true_when_breakdown_missing():
    # Sin neto/impuesto no hay nada que chequear: no se penaliza.
    assert check_amount_consistency(None, None, None, 235.40, tolerance=1.0)


# --- validate_extraction: decisión OK vs REVIEW ---


def test_validate_ok_when_everything_checks_out():
    result = make_result()
    validation = validate_extraction(result, CONFIG)
    assert validation.ok
    assert validation.reasons == []


def test_validate_review_when_illegible():
    result = make_result(legible=False)
    validation = validate_extraction(result, CONFIG)
    assert not validation.ok
    assert any("ilegible" in r for r in validation.reasons)


def test_validate_review_when_missing_amount():
    result = make_result(amount=None)
    validation = validate_extraction(result, CONFIG)
    assert not validation.ok
    assert any("monto" in r for r in validation.reasons)


def test_validate_review_when_missing_currency():
    result = make_result(currency=None)
    validation = validate_extraction(result, CONFIG)
    assert not validation.ok
    assert any("moneda" in r for r in validation.reasons)


def test_validate_review_when_currency_not_allowed():
    result = make_result(currency="GBP")
    validation = validate_extraction(result, CONFIG)
    assert not validation.ok
    assert any("no está en la lista permitida" in r for r in validation.reasons)


def test_validate_review_when_low_overall_confidence():
    result = make_result(confidence={**HIGH_CONF, "overall": 0.3})
    validation = validate_extraction(result, CONFIG)
    assert not validation.ok
    assert any("confianza general baja" in r for r in validation.reasons)


def test_validate_review_when_low_field_confidence():
    result = make_result(confidence={**HIGH_CONF, "amount": 0.2})
    validation = validate_extraction(result, CONFIG)
    assert not validation.ok
    assert any("amount" in r for r in validation.reasons)


def test_validate_review_when_amounts_inconsistent():
    result = make_result(net_amount=100, tax_amount=10, tip_amount=0, amount=200)
    validation = validate_extraction(result, CONFIG)
    assert not validation.ok
    assert any("no coincide" in r for r in validation.reasons)


def test_validate_ok_with_consistent_breakdown():
    result = make_result(
        currency="PEN", net_amount=203.20, tax_amount=0, tip_amount=20.30, amount=223.50
    )
    validation = validate_extraction(result, CONFIG)
    assert validation.ok


def test_validate_review_when_invalid_date_format():
    result = make_result(date="12/06/2026")
    validation = validate_extraction(result, CONFIG)
    assert not validation.ok
    assert any("fecha" in r for r in validation.reasons)


# --- Corrección 2: nunca inventar un código de moneda fuera de la lista de la plantilla ---


def test_unrecognized_currency_normalizes_to_none_and_forces_review():
    # Simula lo que hace main.py: normalizar antes de validar. Una moneda que no está
    # en la lista fija de la plantilla (ej. yenes japoneses) nunca debe "inventarse"
    # como un código nuevo; debe quedar en None y forzar revisión manual.
    allowed = CONFIG["extraction"]["currencies"]
    normalized = currency.normalize_currency_code("JPY", allowed)
    assert normalized is None

    result = make_result(currency=normalized)
    validation = validate_extraction(result, CONFIG)
    assert not validation.ok
    assert any("moneda" in r for r in validation.reasons)


def test_recognized_currency_alias_normalizes_to_allowed_code_and_passes():
    allowed = CONFIG["extraction"]["currencies"]
    normalized = currency.normalize_currency_code("ARS", allowed)  # alias -> código de la plantilla
    assert normalized == "ARG"
    assert normalized in allowed

    result = make_result(currency=normalized)
    validation = validate_extraction(result, CONFIG)
    assert validation.ok


# --- Comments: una boleta sin fecha puede seguir siendo OK (Comments cae al caso
# "solo nombre de archivo", no se rechaza la boleta por esto) ---


def test_validate_ok_when_date_is_missing():
    result = make_result(date=None)
    validation = validate_extraction(result, CONFIG)
    assert validation.ok
