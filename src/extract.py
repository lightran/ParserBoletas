"""Extracción de campos de una boleta usando el modelo de visión de Claude.

El camino principal es visión (no OCR clásico): se envía la imagen ya preprocesada
y se le pide al modelo que devuelva JSON estructurado, incluyendo una confianza
por campo. La llamada a la red está aislada en `_call_vision_api` para poder
mockearla en tests sin necesitar una API key real.
"""

from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

from PIL import Image

SYSTEM_PROMPT = """Eres un asistente que extrae datos de boletas/facturas de gastos de viaje \
de LATAM a partir de una o más imágenes de un mismo comprobante. Respondes ÚNICAMENTE con JSON \
válido, sin texto adicional ni markdown.

Reglas de negocio importantes:
1. Si la imagen contiene DOS documentos (la boleta/factura del comercio y además un voucher \
   de pago con tarjeta, p.ej. izipay/niubiz/transbank/POS), el campo "amount" debe ser el \
   TOTAL final del voucher de tarjeta (que normalmente incluye propina), NO el subtotal o \
   total de la boleta del comercio. En ese caso marca "used_card_voucher_total": true.
2. Si solo hay un documento (factura/boleta/invoice sin voucher separado), "amount" es el \
   total final de ese documento (el que el cliente pagó).
3. Reporta los montos EXACTAMENTE como aparecen impresos, en la moneda original de la \
   transacción. NO conviertas divisas.
4. "currency" debe ser uno de estos códigos exactos: {currencies}. Si no puedes determinar \
   la moneda con confianza, usa null y baja la confianza de ese campo.
5. "expense_type" debe ser una de estas categorías exactas: {expense_types}. Si ninguna \
   calza bien, usa "Miscellaneous" y baja su confianza.
6. "date" es la fecha de la transacción/expense (no una fecha de vencimiento), en formato \
   ISO YYYY-MM-DD.
7. "time" es la hora de emisión impresa en el documento (no una hora de vencimiento), en \
   formato 24h HH:MM. Muchas boletas de taxi o térmicas no traen la hora legible: en ese \
   caso usa null y baja la confianza de ese campo en vez de inventarla.
8. Si la imagen está borrosa, cortada, o ilegible en partes relevantes, marca "legible": false \
   y baja "confidence.overall".

Formato de respuesta JSON exacto:
{{
  "vendor": string|null,
  "tax_id": string|null,
  "document_number": string|null,
  "date": string|null,
  "time": string|null,
  "currency": string|null,
  "amount": number|null,
  "net_amount": number|null,
  "tax_amount": number|null,
  "tip_amount": number|null,
  "expense_type": string|null,
  "used_card_voucher_total": boolean,
  "legible": boolean,
  "notes": string|null,
  "confidence": {{
    "vendor": number, "date": number, "time": number, "currency": number,
    "amount": number, "expense_type": number, "overall": number
  }}
}}
Todos los "confidence.*" son números entre 0.0 y 1.0.
"""


@dataclass
class ExtractionResult:
    vendor: Optional[str] = None
    tax_id: Optional[str] = None
    document_number: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    currency: Optional[str] = None
    amount: Optional[float] = None
    net_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    tip_amount: Optional[float] = None
    expense_type: Optional[str] = None
    used_card_voucher_total: bool = False
    legible: bool = True
    notes: Optional[str] = None
    confidence: dict = field(default_factory=dict)
    raw_response: Optional[str] = None
    error: Optional[str] = None
    usage: dict = field(default_factory=dict)

    def overall_confidence(self) -> float:
        return float(self.confidence.get("overall", 0.0))


def _image_to_base64_jpeg(image: Image.Image, max_dimension_px: int) -> str:
    img = image.convert("RGB")
    w, h = img.size
    if max(w, h) > max_dimension_px:
        scale = max_dimension_px / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _build_system_prompt(config: dict) -> str:
    extraction_cfg = config.get("extraction", {})
    currencies = ", ".join(extraction_cfg.get("currencies", []))
    expense_types = ", ".join(extraction_cfg.get("expense_types", []))
    return SYSTEM_PROMPT.format(currencies=currencies, expense_types=expense_types)


def _call_vision_api(pages: List[Image.Image], config: dict) -> tuple[str, dict]:
    """Llama a la API de Claude y devuelve (texto crudo, usage de la respuesta).

    Aislado en su propia función para poder mockearlo en tests.
    """
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY no está definida. Exporta la variable de entorno "
            "con tu API key antes de correr el pipeline."
        )

    extraction_cfg = config.get("extraction", {})
    max_dim = extraction_cfg.get("max_image_dimension_px", 1568)
    model = extraction_cfg.get("model", "claude-sonnet-5")

    content = []
    for page in pages:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": _image_to_base64_jpeg(page, max_dim),
                },
            }
        )
    content.append(
        {
            "type": "text",
            "text": "Extrae los datos de esta boleta/factura siguiendo las reglas del sistema.",
        }
    )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_build_system_prompt(config),
        messages=[{"role": "user", "content": content}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(response.usage, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }
    return text, usage


def parse_extraction_response(raw_text: str) -> ExtractionResult:
    """Parsea el JSON devuelto por el modelo a un ExtractionResult. No llama a la red."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return ExtractionResult(
            legible=False,
            error=f"respuesta no es JSON válido: {exc}",
            raw_response=raw_text,
            confidence={"overall": 0.0},
        )

    return ExtractionResult(
        vendor=data.get("vendor"),
        tax_id=data.get("tax_id"),
        document_number=data.get("document_number"),
        date=data.get("date"),
        time=data.get("time"),
        currency=data.get("currency"),
        amount=data.get("amount"),
        net_amount=data.get("net_amount"),
        tax_amount=data.get("tax_amount"),
        tip_amount=data.get("tip_amount"),
        expense_type=data.get("expense_type"),
        used_card_voucher_total=bool(data.get("used_card_voucher_total", False)),
        legible=bool(data.get("legible", True)),
        notes=data.get("notes"),
        confidence=data.get("confidence", {}) or {},
        raw_response=raw_text,
    )


def extract_receipt(pages: List[Image.Image], config: dict) -> ExtractionResult:
    """Extrae los campos de una boleta (una o más páginas/imágenes de un mismo documento)."""
    try:
        raw_text, usage = _call_vision_api(pages, config)
    except Exception as exc:  # noqa: BLE001 - se reporta como boleta no procesable
        return ExtractionResult(
            legible=False,
            error=str(exc),
            confidence={"overall": 0.0},
        )
    result = parse_extraction_response(raw_text)
    result.usage = usage
    return result
