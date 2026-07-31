import os

import yaml

import api_key


def test_resolve_api_key_prefers_env_var_over_file(tmp_path, monkeypatch):
    monkeypatch.setenv(api_key.ENV_VAR_NAME, "env-token")
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text("anthropic_api_key: file-token\n", encoding="utf-8")

    result = api_key.resolve_api_key(secrets_path)

    assert result == "env-token"


def test_resolve_api_key_reads_existing_file_without_prompting(tmp_path, monkeypatch):
    monkeypatch.delenv(api_key.ENV_VAR_NAME, raising=False)
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text("anthropic_api_key: saved-token\n", encoding="utf-8")

    def _fail_if_called(prompt=""):
        raise AssertionError("no debería pedir el token si ya está guardado en el archivo")

    monkeypatch.setattr("getpass.getpass", _fail_if_called)

    result = api_key.resolve_api_key(secrets_path)

    assert result == "saved-token"
    assert os.environ[api_key.ENV_VAR_NAME] == "saved-token"


def test_resolve_api_key_prompts_and_saves_when_absent(tmp_path, monkeypatch):
    monkeypatch.delenv(api_key.ENV_VAR_NAME, raising=False)
    secrets_path = tmp_path / "secrets.yaml"
    assert not secrets_path.exists()

    monkeypatch.setattr("getpass.getpass", lambda prompt="": "typed-token")

    result = api_key.resolve_api_key(secrets_path)

    assert result == "typed-token"
    assert os.environ[api_key.ENV_VAR_NAME] == "typed-token"
    assert secrets_path.exists()

    saved = yaml.safe_load(secrets_path.read_text(encoding="utf-8"))
    assert saved["anthropic_api_key"] == "typed-token"


def test_resolve_api_key_reprompts_on_empty_input(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(api_key.ENV_VAR_NAME, raising=False)
    secrets_path = tmp_path / "secrets.yaml"

    responses = iter(["   ", "", "real-token"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(responses))

    result = api_key.resolve_api_key(secrets_path)

    assert result == "real-token"
    assert "vacía" in capsys.readouterr().out.lower()


def test_resolve_api_key_ignores_blank_token_in_file_and_prompts(tmp_path, monkeypatch):
    monkeypatch.delenv(api_key.ENV_VAR_NAME, raising=False)
    secrets_path = tmp_path / "secrets.yaml"
    secrets_path.write_text("anthropic_api_key: ''\n", encoding="utf-8")

    monkeypatch.setattr("getpass.getpass", lambda prompt="": "new-token")

    result = api_key.resolve_api_key(secrets_path)

    assert result == "new-token"


def test_resolve_api_key_writes_file_with_utf8_encoding_and_plaintext_warning(tmp_path, monkeypatch):
    monkeypatch.delenv(api_key.ENV_VAR_NAME, raising=False)
    secrets_path = tmp_path / "secrets.yaml"
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "tok-123")

    api_key.resolve_api_key(secrets_path)

    content = secrets_path.read_text(encoding="utf-8")
    assert "TEXTO PLANO" in content
    assert "tok-123" in content


def test_resolve_api_key_accepts_pathlib_path_in_nested_directory(tmp_path, monkeypatch):
    # Confirma manejo con pathlib.Path (no strings ni separadores hardcodeados),
    # incluyendo creación del directorio contenedor si no existe.
    monkeypatch.delenv(api_key.ENV_VAR_NAME, raising=False)
    secrets_path = tmp_path / "config_dir" / "secrets.yaml"
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "nested-token")

    result = api_key.resolve_api_key(secrets_path)

    assert result == "nested-token"
    assert secrets_path.exists()
