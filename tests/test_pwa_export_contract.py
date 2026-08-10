"""Verifica el round-trip completo del contrato del ZIP: el paquete que arma la
lógica de exportación de la PWA (pwa/js/export-zip.js, corrida tal cual con
Node — no una reimplementación en Python que se pueda desalinear) pasa la
validación real de `receipt_collections.import_collection_from_zip` y se
importa correctamente. Ese es el criterio de aceptación acordado para la PWA:
exportar desde el celular -> importar en el PC -> la colección aparece con sus
boletas.

Se salta si no hay Node disponible o si no se corrió `npm install` en pwa/
(nada del resto de la suite de la app de PC depende de Node)."""

import shutil
import subprocess
from pathlib import Path

import pytest

import receipt_collections as rc

PWA_DIR = Path(__file__).resolve().parent.parent / "pwa"
BUILD_SCRIPT = PWA_DIR / "scripts" / "build_test_zip.js"


@pytest.fixture(autouse=True)
def _isolated_collections_root(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "_collections_root", lambda: tmp_path / "colecciones")


def _node_available() -> bool:
    return shutil.which("node") is not None and (PWA_DIR / "node_modules" / "jszip").exists()


@pytest.mark.skipif(not _node_available(), reason="node y/o pwa/node_modules/jszip no disponibles")
def test_pwa_exported_zip_passes_real_importer(tmp_path):
    output_zip = tmp_path / "pwa-export.zip"
    result = subprocess.run(
        ["node", str(BUILD_SCRIPT), str(output_zip), "Coleccion Prueba PWA"],
        cwd=PWA_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"build_test_zip.js falló:\n{result.stdout}\n{result.stderr}"
    assert output_zip.exists()

    summary = rc.import_collection_from_zip(output_zip)

    assert summary.name == "Coleccion Prueba PWA"
    assert summary.n_receipts == 3
    assert sorted(p.name for p in rc.list_receipts(summary.slug)) == [
        "boleta_clp.jpg",
        "boleta_pen.jpg",
        "boleta_usd.jpg",
    ]

    # El coleccion.json reconstruido queda en el esquema local estándar, igual
    # que cualquier otra colección (ver receipt_collections.py).
    import json

    metadata = json.loads(rc._metadata_path(summary.slug).read_text(encoding="utf-8"))
    assert set(metadata.keys()) == {"version", "name", "created_at", "last_generated_at"}
    assert metadata["version"] == rc.CURRENT_METADATA_VERSION
