#!/usr/bin/env python
"""Genera un ZIP de colección de prueba para validar el importador
(`receipt_collections.import_collection_from_zip`) desde la UI, sin tener que armar
el paquete a mano ni depender de la herramienta del celular (que todavía no existe).

Uso:
    python scripts/generar_coleccion_prueba.py
    python scripts/generar_coleccion_prueba.py --name "Otra colección" --output ruta/salida.zip

Por defecto genera 3 boletas ficticias en monedas distintas (CLP, USD, PEN) — imágenes
simples de texto sobre fondo blanco (emisor, fecha, ítems, total), suficientes para que
el modelo de visión las lea igual que una boleta real y así poder ejercitar el flujo
completo de rendición multi-moneda (Tipo de cambio -> FX real por moneda) importando
esta colección y generando una rendición de prueba de punta a punta.

## Contrato del ZIP (fuente de verdad: la validación real en receipt_collections.py)

Esta es también la especificación de referencia para cualquier otra herramienta que
exporte colecciones en este formato (ej. la futura app de celular):

    <nombre>.zip
    ├── coleccion.json     # ver esquema abajo
    └── boletas/
        ├── boleta_1.jpg
        └── ...

`coleccion.json`:
    {
      "version": 1,                        # entero — debe estar en
                                            # receipt_collections.SUPPORTED_METADATA_VERSIONS
                                            # (hoy solo {1})
      "name": "Nombre visible",            # string no vacío (se sanea para el
                                            # nombre de carpeta, igual que crear
                                            # una colección a mano)
      "receipts": ["boleta_1.jpg", "..."], # lista de nombres de archivo PLANOS
                                            # (sin subcarpetas), extensión en
                                            # .jpg/.jpeg/.png/.pdf — cada uno debe
                                            # existir de verdad en boletas/ dentro
                                            # del zip, y boletas/ no puede tener
                                            # archivos sin declarar acá (salvo
                                            # .DS_Store/Thumbs.db, que se toleran)
      "created_at": "2026-06-15T10:00:00+00:00"  # opcional; no se valida el
                                            # formato, pero debe ser ISO 8601 para
                                            # ser consistente con el resto de la app
    }

`coleccion.json` y `boletas/` van en la RAÍZ del zip, no dentro de una carpeta
contenedora. Cualquier entrada que intente escribir fuera del destino al descomprimir
(rutas "..", absolutas, con letra de unidad) se rechaza — no hace falta que este
generador se preocupe por eso, nunca produce ese tipo de entradas.

`tests/test_generar_coleccion_prueba.py` corre el ZIP generado por este script contra
el importador real, así que si el contrato cambia y este generador queda desalineado,
ese test lo detecta.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import receipt_collections as rc  # noqa: E402 — reusa las constantes del contrato real
from main import _ensure_utf8_console  # noqa: E402 — evita mojibake en consola Windows

DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "fixtures"
DEFAULT_NAME = "Coleccion Prueba Multi Moneda"

IMAGE_SIZE = (800, 1000)
BG_COLOR = "white"
FG_COLOR = "black"
MARGIN = 60


@dataclass
class FakeReceipt:
    filename: str
    vendor: str
    date_label: str  # tal como se muestra en la imagen (no tiene que ser ISO)
    currency: str
    items: List[Tuple[str, str]]  # (descripción, monto formateado)
    total: str  # monto formateado, sin el código de moneda


def _font(size: int) -> ImageFont.ImageFont:
    # Fuente por defecto de Pillow, escalable (Pillow >= 10.1) — nada de depender
    # de un .ttf del sistema que puede no existir en la máquina de otra persona.
    return ImageFont.load_default(size=size)


def _draw_receipt(receipt: FakeReceipt) -> Image.Image:
    """Dibuja una boleta ficticia simple y legible: emisor, fecha, ítems y total
    con la moneda — no es una foto real, solo tiene que ser legible para el
    modelo de visión (vendor/date/currency/amount)."""
    img = Image.new("RGB", IMAGE_SIZE, BG_COLOR)
    draw = ImageDraw.Draw(img)
    width = IMAGE_SIZE[0]
    y = 60

    draw.text((MARGIN, y), receipt.vendor, font=_font(34), fill=FG_COLOR)
    y += 55
    draw.text((MARGIN, y), f"Fecha: {receipt.date_label}", font=_font(22), fill=FG_COLOR)
    y += 45
    draw.line((MARGIN, y, width - MARGIN, y), fill=FG_COLOR, width=2)
    y += 30

    item_font = _font(20)
    for description, amount in receipt.items:
        draw.text((MARGIN, y), description, font=item_font, fill=FG_COLOR)
        bbox = draw.textbbox((0, 0), amount, font=item_font)
        amount_width = bbox[2] - bbox[0]
        draw.text((width - MARGIN - amount_width, y), amount, font=item_font, fill=FG_COLOR)
        y += 34

    y += 20
    draw.line((MARGIN, y, width - MARGIN, y), fill=FG_COLOR, width=2)
    y += 34

    draw.text((MARGIN, y), f"TOTAL: {receipt.total} {receipt.currency}", font=_font(30), fill=FG_COLOR)

    return img


def default_receipts() -> List[FakeReceipt]:
    """Tres boletas ficticias en CLP/USD/PEN — pensadas para ejercitar el flujo
    multi-moneda completo (USD se pregunta directo; PEN necesita el cálculo de
    FX real vía Complementary Info) al generar la rendición."""
    return [
        FakeReceipt(
            filename="almuerzo_los_andes_clp.jpg",
            vendor="Restaurante Los Andes",
            date_label="10/06/2026",
            currency="CLP",
            items=[("Almuerzo ejecutivo x2", "$16.000"), ("Bebidas", "$2.500")],
            total="$18.500",
        ),
        FakeReceipt(
            filename="cafe_aeropuerto_usd.jpg",
            vendor="Airport Coffee Shop",
            date_label="11/06/2026",
            currency="USD",
            items=[("Coffee", "$4.50"), ("Sandwich", "$8.00")],
            total="$12.50",
        ),
        FakeReceipt(
            filename="restaurante_lima_pen.jpg",
            vendor="Restaurante Lima Sabor",
            date_label="12/06/2026",
            currency="PEN",
            items=[("Menu ejecutivo", "S/35.00"), ("Bebida", "S/10.00")],
            total="S/45.00",
        ),
    ]


def build_collection_zip(
    output_path: Path,
    *,
    name: str = DEFAULT_NAME,
    receipts: Optional[List[FakeReceipt]] = None,
) -> Path:
    """Arma el .zip en `output_path` con el contrato exacto que exige
    `receipt_collections.import_collection_from_zip` — ver el docstring del
    módulo para el detalle campo por campo."""
    receipts = receipts if receipts is not None else default_receipts()

    manifest = {
        "version": rc.CURRENT_METADATA_VERSION,
        "name": name,
        "receipts": [receipt.filename for receipt in receipts],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", ZIP_DEFLATED) as zf:
        zf.writestr(rc.METADATA_FILENAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        for receipt in receipts:
            image = _draw_receipt(receipt)
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=90)
            zf.writestr(f"{rc.BOLETAS_DIRNAME}/{receipt.filename}", buffer.getvalue())

    return output_path


def main() -> None:
    _ensure_utf8_console()

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--name", default=DEFAULT_NAME, help="Nombre visible de la colección")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help=f"Ruta del .zip a generar (default: {DEFAULT_OUTPUT_DIR}/<nombre saneado>.zip)",
    )
    args = parser.parse_args()

    output_path = args.output
    if output_path is None:
        slug = rc.slugify(args.name) or "coleccion_prueba"
        output_path = DEFAULT_OUTPUT_DIR / f"{slug}.zip"

    build_collection_zip(output_path, name=args.name)

    print(f"Colección de prueba generada: {output_path.resolve()}")
    print('Para importarla: en la app, Colecciones -> "Importar colección (ZIP)".')


if __name__ == "__main__":
    main()
