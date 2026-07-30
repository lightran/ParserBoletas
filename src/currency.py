"""Parsing de montos con formato numérico localizado y detección/normalización de moneda.

Regla de desambiguación de separadores (independiente del idioma):
- Si aparecen '.' y ',' en el mismo número, el símbolo que aparece último (más a la
  derecha) es el separador decimal; el otro se trata como separador de miles.
- Si aparece un solo tipo de símbolo, se interpreta como separador de miles cuando el
  último grupo tiene 3 dígitos (o hay más de una ocurrencia), y como separador decimal
  cuando el último grupo tiene 1 o 2 dígitos y aparece una sola vez.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

# Códigos de moneda exactos que acepta la plantilla (hoja "Cheat Sheet").
# Nota: la plantilla usa "ARG" (no el código ISO-4217 "ARS") para pesos argentinos.
ALLOWED_CURRENCIES = ("CLP", "USD", "BRL", "ARG", "PEN", "COP", "EUR")

_CURRENCY_ALIASES = {
    "ARS": "ARG",
    "PESOS ARGENTINOS": "ARG",
    "ARG$": "ARG",
    "S/": "PEN",
    "S/.": "PEN",
    "SOL": "PEN",
    "SOLES": "PEN",
    "NUEVOS SOLES": "PEN",
    "PEN": "PEN",
    "CLP": "CLP",
    "CLP$": "CLP",
    "PESOS CHILENOS": "CLP",
    "PESO CHILENO": "CLP",
    "US$": "USD",
    "USD$": "USD",
    "USD": "USD",
    "DOLARES": "USD",
    "DÓLARES": "USD",
    "DOLARES AMERICANOS": "USD",
    "DÓLARES AMERICANOS": "USD",
    "US DOLLAR": "USD",
    "US DOLLARS": "USD",
    "R$": "BRL",
    "BRL": "BRL",
    "REAL": "BRL",
    "REALES": "BRL",
    "REAIS": "BRL",
    "COP": "COP",
    "COL$": "COP",
    "PESOS COLOMBIANOS": "COP",
    "PESO COLOMBIANO": "COP",
    "EUR": "EUR",
    "EURO": "EUR",
    "EUROS": "EUR",
    "€": "EUR",
}

_NUMBER_RE = re.compile(r"-?\d[\d.,]*\d|-?\d")


class CurrencyParseError(ValueError):
    pass


def normalize_currency_code(raw: str, allowed=ALLOWED_CURRENCIES) -> Optional[str]:
    """Mapea un símbolo/código/nombre de moneda detectado al código fijo de la plantilla.

    Devuelve None si no se puede reconocer la moneda.
    """
    if not raw:
        return None
    key = raw.strip().upper()
    if key in allowed:
        return key
    if key in _CURRENCY_ALIASES:
        mapped = _CURRENCY_ALIASES[key]
        return mapped if mapped in allowed else None
    return None


def parse_localized_amount(raw: str) -> Decimal:
    """Convierte un string de monto con formato numérico localizado a Decimal limpio.

    Acepta strings con símbolos de moneda, espacios, y separadores de miles/decimales
    en cualquiera de los dos formatos comunes en LATAM (1.234,56 o 1,234.56).
    """
    if raw is None:
        raise CurrencyParseError("raw amount is None")

    text = raw.strip()
    match = _NUMBER_RE.search(text)
    if not match:
        raise CurrencyParseError(f"no se encontró un número en: {raw!r}")
    number = match.group(0)

    negative = number.startswith("-")
    if negative:
        number = number[1:]

    has_dot = "." in number
    has_comma = "," in number

    if has_dot and has_comma:
        last_dot = number.rfind(".")
        last_comma = number.rfind(",")
        if last_comma > last_dot:
            decimal_sep, thousands_sep = ",", "."
        else:
            decimal_sep, thousands_sep = ".", ","
        integer_part, _, fraction_part = number.rpartition(decimal_sep)
        integer_part = integer_part.replace(thousands_sep, "")
        cleaned = f"{integer_part}.{fraction_part}"
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        groups = number.split(sep)
        last_group = groups[-1]
        if len(groups) == 2 and len(last_group) in (1, 2):
            # Una sola ocurrencia con 1-2 dígitos al final: separador decimal.
            cleaned = f"{groups[0]}.{last_group}"
        else:
            # Varias ocurrencias, o último grupo de 3 dígitos: separadores de miles.
            cleaned = "".join(groups)
    else:
        cleaned = number

    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise CurrencyParseError(f"no se pudo parsear el monto: {raw!r}") from exc

    return -value if negative else value
