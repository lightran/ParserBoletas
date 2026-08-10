"""Confirma que scripts/generar_coleccion_prueba.py y receipt_collections.py están
en sincronía: el ZIP que produce el generador tiene que pasar la validación real
del importador y quedar reconstruido con el formato local esperado. Si el
contrato del ZIP cambia en receipt_collections.py y el generador queda
desalineado, este test lo detecta en vez de fallar recién al probarlo a mano
desde la UI.
"""

import json
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import receipt_collections as rc
import generar_coleccion_prueba as gen


@pytest.fixture(autouse=True)
def _isolated_collections_root(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "_collections_root", lambda: tmp_path / "colecciones")


def test_generated_zip_has_expected_structure(tmp_path):
    zip_path = gen.build_collection_zip(tmp_path / "prueba.zip", name="Coleccion Prueba Multi Moneda")

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("coleccion.json"))

    assert names == {
        "coleccion.json",
        "boletas/almuerzo_los_andes_clp.jpg",
        "boletas/cafe_aeropuerto_usd.jpg",
        "boletas/restaurante_lima_pen.jpg",
    }
    assert manifest["version"] == rc.CURRENT_METADATA_VERSION
    assert manifest["name"] == "Coleccion Prueba Multi Moneda"
    assert set(manifest["receipts"]) == {
        "almuerzo_los_andes_clp.jpg",
        "cafe_aeropuerto_usd.jpg",
        "restaurante_lima_pen.jpg",
    }
    assert "created_at" in manifest


def test_generated_zip_imports_successfully_via_real_importer(tmp_path):
    zip_path = gen.build_collection_zip(tmp_path / "prueba.zip", name="Coleccion Prueba Multi Moneda")

    summary = rc.import_collection_from_zip(zip_path)

    assert summary.slug == "Coleccion_Prueba_Multi_Moneda"
    assert summary.n_receipts == 3
    assert sorted(p.name for p in rc.list_receipts(summary.slug)) == [
        "almuerzo_los_andes_clp.jpg",
        "cafe_aeropuerto_usd.jpg",
        "restaurante_lima_pen.jpg",
    ]

    # El coleccion.json reconstruido sigue el esquema local estándar (sin "receipts").
    metadata = json.loads(rc._metadata_path(summary.slug).read_text(encoding="utf-8"))
    assert set(metadata.keys()) == {"version", "name", "created_at", "last_generated_at"}


def test_generated_receipts_are_readable_images_with_distinct_currencies():
    receipts = gen.default_receipts()
    currencies = {r.currency for r in receipts}
    assert currencies == {"CLP", "USD", "PEN"}

    for receipt in receipts:
        image = gen._draw_receipt(receipt)
        assert image.size == gen.IMAGE_SIZE
        # No queda completamente en blanco: efectivamente se dibujó texto.
        assert image.getcolors(maxcolors=2) is None or len(image.getcolors(maxcolors=1_000_000)) > 1


def test_custom_output_path_is_respected(tmp_path):
    custom_path = tmp_path / "nested" / "custom.zip"
    result = gen.build_collection_zip(custom_path, name="Otra Coleccion")
    assert result == custom_path
    assert custom_path.exists()
