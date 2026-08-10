import io
import json
import zipfile
from pathlib import Path

import pytest

import receipt_collections as rc


@pytest.fixture(autouse=True)
def _isolated_collections_root(tmp_path, monkeypatch):
    # Se redirige solo la raíz de colecciones/ (no paths.PROJECT_ROOT entero, que
    # también resuelve recursos de solo lectura vía resource_path()) para no
    # crear/tocar una carpeta colecciones/ real del repo durante los tests.
    monkeypatch.setattr(rc, "_collections_root", lambda: tmp_path / "colecciones")


def _build_zip(name="Viaje Lima", receipts=None, *, version=1, extra_entries=None, created_at=None):
    """Arma en memoria un .zip con el contrato de import (coleccion.json +
    boletas/), sin depender de ninguna herramienta externa — mismo formato que
    debería producir la app del celular."""
    if receipts is None:
        receipts = {"a.jpg": b"contenido-a", "b.jpg": b"contenido-b"}
    manifest = {"version": version, "name": name, "receipts": list(receipts.keys())}
    if created_at is not None:
        manifest["created_at"] = created_at

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("coleccion.json", json.dumps(manifest))
        for filename, content in receipts.items():
            zf.writestr(f"boletas/{filename}", content)
        for arcname, content in (extra_entries or {}).items():
            zf.writestr(arcname, content)
    buf.seek(0)
    return buf


# --- create_collection ---------------------------------------------------------


def test_create_collection_creates_folder_structure_and_metadata():
    summary = rc.create_collection("Gastos Viaje Peru Julio 2026")

    assert summary.slug == "Gastos_Viaje_Peru_Julio_2026"
    assert summary.name == "Gastos Viaje Peru Julio 2026"
    assert summary.n_receipts == 0
    assert summary.last_generated_at is None

    assert rc.boletas_dir(summary.slug).is_dir()
    assert rc._metadata_path(summary.slug).exists()


def test_create_collection_rejects_blank_name():
    with pytest.raises(ValueError):
        rc.create_collection("   ")


def test_create_collection_rejects_duplicate_slug():
    rc.create_collection("Viaje Lima")
    with pytest.raises(rc.CollectionAlreadyExistsError):
        rc.create_collection("Viaje Lima")


def test_create_collection_visible_name_keeps_accents_and_spaces_folder_is_sanitized():
    summary = rc.create_collection("Rendición Perú: viaje/junio")
    assert summary.name == "Rendición Perú: viaje/junio"
    assert "/" not in summary.slug and ":" not in summary.slug


# --- list_collections / get_collection ------------------------------------------


def test_list_collections_empty_when_none_created():
    assert rc.list_collections() == []


def test_list_collections_returns_all_created():
    rc.create_collection("Viaje A")
    rc.create_collection("Viaje B")
    slugs = {c.slug for c in rc.list_collections()}
    assert slugs == {"Viaje_A", "Viaje_B"}


def test_get_collection_unknown_slug_raises_not_found():
    with pytest.raises(rc.CollectionNotFoundError):
        rc.get_collection("no-existe")


# --- add / remove / replace receipts ---------------------------------------------


def test_add_receipt_persists_file_and_updates_count():
    summary = rc.create_collection("Viaje Lima")
    rc.add_receipt(summary.slug, "boleta1.jpg", b"fake-bytes")

    receipts = rc.list_receipts(summary.slug)
    assert [p.name for p in receipts] == ["boleta1.jpg"]
    assert (rc.boletas_dir(summary.slug) / "boleta1.jpg").read_bytes() == b"fake-bytes"
    assert rc.get_collection(summary.slug).n_receipts == 1


def test_add_receipt_unknown_collection_raises_not_found():
    with pytest.raises(rc.CollectionNotFoundError):
        rc.add_receipt("no-existe", "a.jpg", b"x")


def test_remove_receipt_deletes_file_and_updates_count():
    summary = rc.create_collection("Viaje Lima")
    rc.add_receipt(summary.slug, "a.jpg", b"x")
    rc.add_receipt(summary.slug, "b.jpg", b"y")

    rc.remove_receipt(summary.slug, "a.jpg")

    receipts = [p.name for p in rc.list_receipts(summary.slug)]
    assert receipts == ["b.jpg"]
    assert rc.get_collection(summary.slug).n_receipts == 1


def test_remove_receipt_missing_file_is_a_noop():
    summary = rc.create_collection("Viaje Lima")
    rc.remove_receipt(summary.slug, "no-estaba.jpg")  # no debe lanzar


def test_replace_receipt_removes_old_and_adds_new_content():
    summary = rc.create_collection("Viaje Lima")
    rc.add_receipt(summary.slug, "borrosa.jpg", b"vieja")

    rc.replace_receipt(summary.slug, "borrosa.jpg", "nitida.jpg", b"nueva")

    receipts = {p.name: p for p in rc.list_receipts(summary.slug)}
    assert "borrosa.jpg" not in receipts
    assert receipts["nitida.jpg"].read_bytes() == b"nueva"


def test_replace_receipt_same_filename_overwrites_content():
    summary = rc.create_collection("Viaje Lima")
    rc.add_receipt(summary.slug, "a.jpg", b"vieja")

    rc.replace_receipt(summary.slug, "a.jpg", "a.jpg", b"nueva")

    receipts = rc.list_receipts(summary.slug)
    assert [p.name for p in receipts] == ["a.jpg"]
    assert receipts[0].read_bytes() == b"nueva"


# --- rename_receipt -------------------------------------------------------------


def test_rename_receipt_changes_stem_and_preserves_extension_and_content():
    summary = rc.create_collection("Viaje Lima")
    rc.add_receipt(summary.slug, "IMG_20260615_142033.jpg", b"foto")

    # sanitize_receipt_name (no sanitize_filename_component): preserva espacios,
    # porque este nombre termina siendo la Comments de la boleta en el Excel.
    new_path = rc.rename_receipt(summary.slug, "IMG_20260615_142033.jpg", "Almuerzo cliente X")

    assert new_path.name == "Almuerzo cliente X.jpg"
    receipts = {p.name: p for p in rc.list_receipts(summary.slug)}
    assert "IMG_20260615_142033.jpg" not in receipts
    assert receipts["Almuerzo cliente X.jpg"].read_bytes() == b"foto"


def test_rename_receipt_sanitizes_new_name():
    summary = rc.create_collection("Viaje Lima")
    rc.add_receipt(summary.slug, "a.jpg", b"x")

    new_path = rc.rename_receipt(summary.slug, "a.jpg", "Almuerzo / cliente: X")

    assert "/" not in new_path.name and ":" not in new_path.name
    assert new_path.suffix == ".jpg"


def test_rename_receipt_rejects_blank_result():
    summary = rc.create_collection("Viaje Lima")
    rc.add_receipt(summary.slug, "a.jpg", b"x")

    with pytest.raises(ValueError):
        rc.rename_receipt(summary.slug, "a.jpg", "   ")


def test_rename_receipt_missing_file_raises_not_found():
    summary = rc.create_collection("Viaje Lima")
    with pytest.raises(FileNotFoundError):
        rc.rename_receipt(summary.slug, "no-existe.jpg", "nuevo-nombre")


def test_rename_receipt_collision_with_existing_file_raises():
    summary = rc.create_collection("Viaje Lima")
    rc.add_receipt(summary.slug, "a.jpg", b"x")
    rc.add_receipt(summary.slug, "b.jpg", b"y")

    with pytest.raises(FileExistsError):
        rc.rename_receipt(summary.slug, "a.jpg", "b")


def test_rename_receipt_to_same_name_is_a_noop():
    summary = rc.create_collection("Viaje Lima")
    rc.add_receipt(summary.slug, "a.jpg", b"x")

    new_path = rc.rename_receipt(summary.slug, "a.jpg", "a")

    assert new_path.name == "a.jpg"
    assert [p.name for p in rc.list_receipts(summary.slug)] == ["a.jpg"]


# --- persistencia entre "reinicios" (releer desde disco sin estado en memoria) ---


def test_collection_persists_across_fresh_reads():
    summary = rc.create_collection("Viaje Persistente")
    rc.add_receipt(summary.slug, "a.jpg", b"x")

    # Nada de lo anterior queda en memoria de por sí — get_collection/list_receipts
    # siempre leen del disco, así que esto reproduce "reabrir" la colección.
    reloaded = rc.get_collection(summary.slug)
    assert reloaded.name == "Viaje Persistente"
    assert reloaded.n_receipts == 1
    assert [p.name for p in rc.list_receipts(summary.slug)] == ["a.jpg"]


# --- mark_generated --------------------------------------------------------------


def test_mark_generated_sets_timestamp_without_touching_name_or_created_at():
    summary = rc.create_collection("Viaje Lima")
    assert summary.last_generated_at is None

    rc.mark_generated(summary.slug)

    updated = rc.get_collection(summary.slug)
    assert updated.last_generated_at is not None
    assert updated.name == summary.name
    assert updated.created_at == summary.created_at


# --- create_collection ahora versiona la metadata -------------------------------


def test_create_collection_writes_current_metadata_version():
    summary = rc.create_collection("Viaje Lima")
    metadata = json.loads(rc._metadata_path(summary.slug).read_text(encoding="utf-8"))
    assert metadata["version"] == rc.CURRENT_METADATA_VERSION


# --- import_collection_from_zip: caso nuevo -------------------------------------


def test_import_creates_new_collection_matching_local_format():
    summary = rc.import_collection_from_zip(_build_zip("Viaje Lima Importado"))

    assert summary.slug == "Viaje_Lima_Importado"
    assert summary.name == "Viaje Lima Importado"
    assert summary.n_receipts == 2
    assert sorted(p.name for p in rc.list_receipts(summary.slug)) == ["a.jpg", "b.jpg"]

    # El coleccion.json reconstruido sigue el mismo esquema que una colección
    # creada a mano (version/name/created_at/last_generated_at, sin "receipts").
    metadata = json.loads(rc._metadata_path(summary.slug).read_text(encoding="utf-8"))
    assert set(metadata.keys()) == {"version", "name", "created_at", "last_generated_at"}
    assert metadata["version"] == rc.CURRENT_METADATA_VERSION
    assert metadata["last_generated_at"] is None

    # rendiciones/ también existe, igual que create_collection la deja implícita
    # (se crea recién al generar) — acá se crea de una para que "generar
    # rendición" funcione igual sin pasos extra.
    assert rc.rendiciones_dir(summary.slug).is_dir()


def test_import_preserves_created_at_from_manifest_when_present():
    summary = rc.import_collection_from_zip(
        _build_zip("Viaje Lima", created_at="2026-01-01T00:00:00+00:00")
    )
    assert summary.created_at == "2026-01-01T00:00:00+00:00"


def test_import_no_staging_leftovers_after_success(tmp_path):
    rc.import_collection_from_zip(_build_zip("Viaje Lima"))
    staging_root = rc._collections_root() / rc._IMPORT_STAGING_DIRNAME
    assert list(staging_root.iterdir()) == []


def test_import_does_not_pollute_list_collections_with_staging_dir():
    rc.import_collection_from_zip(_build_zip("Viaje Lima"))
    assert [c.slug for c in rc.list_collections()] == ["Viaje_Lima"]


# --- import_collection_from_zip: reemplazo + confirmación -----------------------


def test_import_existing_collection_without_replace_raises_and_keeps_old_content():
    rc.create_collection("Viaje Lima")
    rc.add_receipt("Viaje_Lima", "old.jpg", b"old-content")

    with pytest.raises(rc.CollectionAlreadyExistsError):
        rc.import_collection_from_zip(_build_zip("Viaje Lima", {"new.jpg": b"new"}))

    assert [p.name for p in rc.list_receipts("Viaje_Lima")] == ["old.jpg"]


def test_import_with_replace_existing_discards_old_content_entirely():
    rc.create_collection("Viaje Lima")
    rc.add_receipt("Viaje_Lima", "old.jpg", b"old-content")
    rc.add_receipt("Viaje_Lima", "keep-me-out.jpg", b"should be gone")

    summary = rc.import_collection_from_zip(
        _build_zip("Viaje Lima", {"new.jpg": b"new-content"}), replace_existing=True
    )

    assert summary.slug == "Viaje_Lima"
    assert [p.name for p in rc.list_receipts("Viaje_Lima")] == ["new.jpg"]


def test_import_replace_rollback_keeps_existing_collection_if_swap_fails(monkeypatch):
    rc.create_collection("Viaje Lima")
    rc.add_receipt("Viaje_Lima", "old.jpg", b"old-content")

    original_rename = Path.rename
    calls = {"n": 0}

    def flaky_rename(self, target):
        calls["n"] += 1
        if calls["n"] == 2:
            # La primera llamada mueve la colección vieja a un backup (debe
            # tener éxito); la segunda es el swap final staging -> destino
            # final, que acá se simula fallando.
            raise OSError("simulated failure moving staging into place")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky_rename)

    with pytest.raises(OSError):
        rc.import_collection_from_zip(
            _build_zip("Viaje Lima", {"new.jpg": b"new-content"}), replace_existing=True
        )

    # La colección original debe seguir exactamente como estaba.
    assert [p.name for p in rc.list_receipts("Viaje_Lima")] == ["old.jpg"]
    assert (rc.boletas_dir("Viaje_Lima") / "old.jpg").read_bytes() == b"old-content"
    # No debe quedar ninguna carpeta de backup huérfana.
    leftovers = [p.name for p in rc._collections_root().iterdir() if "backup" in p.name]
    assert leftovers == []


# --- import_collection_from_zip: validación --------------------------------------


def test_import_rejects_corrupt_zip():
    with pytest.raises(rc.InvalidCollectionArchiveError):
        rc.import_collection_from_zip(io.BytesIO(b"not a zip file at all"))


def test_import_rejects_missing_coleccion_json():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("boletas/a.jpg", b"x")
    buf.seek(0)
    with pytest.raises(rc.InvalidCollectionArchiveError, match="coleccion.json"):
        rc.import_collection_from_zip(buf)


def test_import_rejects_invalid_json():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("coleccion.json", "{not valid json")
        zf.writestr("boletas/a.jpg", b"x")
    buf.seek(0)
    with pytest.raises(rc.InvalidCollectionArchiveError):
        rc.import_collection_from_zip(buf)


def test_import_rejects_unsupported_version():
    with pytest.raises(rc.InvalidCollectionArchiveError, match="[Vv]ersi"):
        rc.import_collection_from_zip(_build_zip("Viaje Lima", version=999))


def test_import_rejects_missing_name():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("coleccion.json", json.dumps({"version": 1, "receipts": ["a.jpg"]}))
        zf.writestr("boletas/a.jpg", b"x")
    buf.seek(0)
    with pytest.raises(rc.InvalidCollectionArchiveError):
        rc.import_collection_from_zip(buf)


def test_import_rejects_missing_boletas_folder():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("coleccion.json", json.dumps({"version": 1, "name": "X", "receipts": ["a.jpg"]}))
    buf.seek(0)
    with pytest.raises(rc.InvalidCollectionArchiveError, match="boletas"):
        rc.import_collection_from_zip(buf)


def test_import_rejects_incomplete_zip_missing_declared_receipt():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "coleccion.json",
            json.dumps({"version": 1, "name": "X", "receipts": ["a.jpg", "b.jpg"]}),
        )
        zf.writestr("boletas/a.jpg", b"x")  # falta b.jpg
    buf.seek(0)
    with pytest.raises(rc.InvalidCollectionArchiveError, match="incompleto"):
        rc.import_collection_from_zip(buf)


def test_import_rejects_unexpected_extra_file_not_in_manifest():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("coleccion.json", json.dumps({"version": 1, "name": "X", "receipts": ["a.jpg"]}))
        zf.writestr("boletas/a.jpg", b"x")
        zf.writestr("boletas/sorpresa.jpg", b"y")
    buf.seek(0)
    with pytest.raises(rc.InvalidCollectionArchiveError, match="no declarados"):
        rc.import_collection_from_zip(buf)


def test_import_ignores_known_junk_files_like_ds_store():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("coleccion.json", json.dumps({"version": 1, "name": "X", "receipts": ["a.jpg"]}))
        zf.writestr("boletas/a.jpg", b"x")
        zf.writestr("boletas/.DS_Store", b"junk")
    buf.seek(0)
    summary = rc.import_collection_from_zip(buf)
    assert [p.name for p in rc.list_receipts(summary.slug)] == ["a.jpg"]


def test_import_rejects_unsupported_extension_in_manifest():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("coleccion.json", json.dumps({"version": 1, "name": "X", "receipts": ["a.txt"]}))
        zf.writestr("boletas/a.txt", b"x")
    buf.seek(0)
    with pytest.raises(rc.InvalidCollectionArchiveError):
        rc.import_collection_from_zip(buf)


def test_import_rejects_blank_name_after_sanitizing():
    with pytest.raises(rc.InvalidCollectionArchiveError):
        rc.import_collection_from_zip(_build_zip(name="***"))


# --- import_collection_from_zip: path traversal (zip-slip) ----------------------


def test_import_rejects_path_traversal_parent_dir(tmp_path):
    zip_buf = _build_zip("Viaje Lima", extra_entries={"../evil.txt": b"pwned"})
    with pytest.raises(rc.InvalidCollectionArchiveError, match="insegura"):
        rc.import_collection_from_zip(zip_buf)

    # Nada debe haberse escrito fuera del árbol de colecciones/.
    collections_root = rc._collections_root()
    assert not (collections_root.parent / "evil.txt").exists()
    assert "Viaje_Lima" not in [c.slug for c in rc.list_collections()]


def test_import_rejects_path_traversal_absolute_path(tmp_path):
    outside_target = tmp_path / "outside-evil.txt"
    # En algunos sistemas de archivos, una entrada de zip con ruta absoluta de
    # Windows no es un nombre de archivo válido dentro de un .zip común, pero
    # zipfile permite escribir cualquier string como nombre de entrada — se
    # construye igual para probar que el importador nunca confía en eso.
    zip_buf = _build_zip(
        "Viaje Lima", extra_entries={str(outside_target): b"pwned"}
    )
    with pytest.raises(rc.InvalidCollectionArchiveError, match="insegura"):
        rc.import_collection_from_zip(zip_buf)
    assert not outside_target.exists()
