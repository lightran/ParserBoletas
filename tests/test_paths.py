import sys

import paths


def test_resource_path_dev_mode_resolves_against_project_root(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    result = paths.resource_path("plantilla/foo.xlsx")
    assert result == paths.PROJECT_ROOT / "plantilla/foo.xlsx"


def test_resource_path_frozen_resolves_against_meipass(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    result = paths.resource_path("plantilla/foo.xlsx")
    assert result == tmp_path / "plantilla/foo.xlsx"


def test_writable_path_dev_mode_resolves_against_project_root(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    result = paths.writable_path("config.yaml")
    assert result == paths.PROJECT_ROOT / "config.yaml"


def test_writable_path_frozen_resolves_next_to_executable(monkeypatch, tmp_path):
    fake_exe = tmp_path / "ParserBoletas.exe"
    fake_exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    result = paths.writable_path("config.yaml")
    assert result == tmp_path / "config.yaml"


def test_is_frozen_reflects_sys_frozen_attribute(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert paths.is_frozen() is True

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert paths.is_frozen() is False
