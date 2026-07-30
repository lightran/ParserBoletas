"""Validación de consistencia de montos y umbral de confianza.

No calcula ni escribe columnas nuevas en el Excel: solo decide si una boleta
queda OK o se marca para revisión manual, y por qué.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as date_cls
from decimal import Decimal
from typing import List

from extract import ExtractionResult

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ValidationResult:
    status: str  # "OK" o "REVIEW"
    reasons: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "OK"


def _is_valid_iso_date(value) -> bool:
    if not value or not isinstance(value, str) or not ISO_DATE_RE.match(value):
        return False
    try:
        date_cls.fromisoformat(value)
        return True
    except ValueError:
        return False


def check_amount_consistency(
    net_amount, tax_amount, tip_amount, amount, tolerance: float
) -> bool:
    """True si neto + impuesto (+ propina) ≈ total dentro de la tolerancia.

    Si no hay suficiente desglose (neto o impuesto ausentes), no hay nada que
    chequear y se considera consistente (no se penaliza por falta de desglose).
    """
    if net_amount is None or tax_amount is None or amount is None:
        return True
    expected = Decimal(str(net_amount)) + Decimal(str(tax_amount)) + Decimal(str(tip_amount or 0))
    return abs(expected - Decimal(str(amount))) <= Decimal(str(tolerance))


def validate_extraction(result: ExtractionResult, config: dict) -> ValidationResult:
    reasons: List[str] = []
    validation_cfg = config.get("validation", {})
    min_field_conf = validation_cfg.get("min_field_confidence", 0.6)
    min_overall_conf = validation_cfg.get("min_overall_confidence", 0.6)
    tolerance = validation_cfg.get("amount_consistency_tolerance", 1.0)
    allowed_currencies = config.get("extraction", {}).get("currencies", [])

    if result.error:
        reasons.append(f"error de extracción: {result.error}")
    if not result.legible:
        reasons.append("imagen marcada como ilegible por el modelo")

    if result.amount is None:
        reasons.append("no se pudo determinar el monto")
    if result.currency is None:
        reasons.append("no se pudo determinar la moneda")
    elif allowed_currencies and result.currency not in allowed_currencies:
        reasons.append(f"moneda '{result.currency}' no está en la lista permitida")

    if result.date is not None and not _is_valid_iso_date(result.date):
        reasons.append(f"fecha con formato inválido: {result.date!r}")

    overall = result.overall_confidence()
    if overall < min_overall_conf:
        reasons.append(f"confianza general baja ({overall:.2f} < {min_overall_conf})")

    for fld in ("amount", "currency", "date", "expense_type"):
        conf = float(result.confidence.get(fld, 1.0))
        if conf < min_field_conf:
            reasons.append(f"confianza baja en '{fld}' ({conf:.2f} < {min_field_conf})")

    if not check_amount_consistency(
        result.net_amount, result.tax_amount, result.tip_amount, result.amount, tolerance
    ):
        reasons.append("neto + impuesto (+ propina) no coincide con el monto total")

    status = "REVIEW" if reasons else "OK"
    return ValidationResult(status=status, reasons=reasons)
