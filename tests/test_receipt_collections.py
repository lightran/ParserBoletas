import pytest

import receipt_collections as rc


@pytest.fixture(autouse=True)
def _isolated_collections_root(tmp_path, monkeypatch):
    # Se redirige solo la raíz de colecciones/ (no paths.PROJECT_ROOT entero, que
    # también resuelve recursos de solo lectura vía resource_path()) para no
    # crear/tocar una carpeta colecciones/ real del repo durante los tests.
    monkeypatch.setattr(rc, "_collections_root", lambda: tmp_path / "colecciones")


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
