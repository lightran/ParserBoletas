"""Resuelve la API key de Anthropic con esta prioridad:

1. Variable de entorno ANTHROPIC_API_KEY, si ya está definida.
2. El archivo de secretos local, si tiene un token guardado.
3. La pide por consola (sin eco, vía getpass) y la guarda en el archivo de
   secretos para las próximas ejecuciones.

ADVERTENCIA DE SEGURIDAD: el archivo de secretos guarda la API key en TEXTO PLANO
en disco (es la única forma simple de persistirla localmente). No lo subas al
control de versiones — ya está listado en .gitignore — y protege el acceso a esta
carpeta como corresponda. No compartas su contenido en tickets, chats ni logs.
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Optional

import yaml

ENV_VAR_NAME = "ANTHROPIC_API_KEY"
SECRETS_KEY = "anthropic_api_key"
DEFAULT_SECRETS_PATH = Path("secrets.yaml")

_SECRETS_FILE_HEADER = (
    "# Archivo de secretos local -- NO subir a git (ya esta en .gitignore).\n"
    "# La API key queda en TEXTO PLANO en este archivo. Protege el acceso a esta\n"
    "# carpeta y no compartas su contenido en tickets, chats ni logs.\n"
)


def _read_token_from_file(secrets_path: Path) -> Optional[str]:
    if not secrets_path.exists():
        return None
    with open(secrets_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    token = data.get(SECRETS_KEY)
    return token.strip() if isinstance(token, str) and token.strip() else None


def _write_token_to_file(secrets_path: Path, token: str) -> None:
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    with open(secrets_path, "w", encoding="utf-8") as f:
        f.write(_SECRETS_FILE_HEADER)
        yaml.safe_dump({SECRETS_KEY: token}, f, allow_unicode=True)
    try:
        # Restringe el acceso al archivo. Best-effort: en Windows los bits de
        # permisos POSIX no aplican de la misma forma, así que se ignora el error.
        os.chmod(secrets_path, 0o600)
    except OSError:
        pass


def _prompt_for_token() -> str:
    while True:
        entered = getpass.getpass(
            "No se encontró la API key de Anthropic. Ingrésala "
            "(no se mostrará en pantalla): "
        ).strip()
        if entered:
            return entered
        print("La API key no puede quedar vacía. Intenta de nuevo.")


def has_saved_key(secrets_path: Path = DEFAULT_SECRETS_PATH) -> bool:
    """True si ya hay una API key utilizable (env var o archivo de secretos), sin
    pedirla ni bloquear. Usado por la interfaz web para decidir si mostrar el campo
    de token en el formulario."""
    env_value = os.environ.get(ENV_VAR_NAME)
    if env_value and env_value.strip():
        return True
    return _read_token_from_file(Path(secrets_path)) is not None


def save_api_key(token: str, secrets_path: Path = DEFAULT_SECRETS_PATH) -> None:
    """Guarda `token` en el archivo de secretos y lo deja seteado en el proceso.
    Mismo criterio de persistencia que `resolve_api_key` (texto plano, chmod 600
    best-effort, archivo gitignoreado) — pensado para la interfaz web, donde el
    token llega como campo de formulario en vez de por `getpass`."""
    token = token.strip()
    if not token:
        raise ValueError("La API key no puede quedar vacía.")
    _write_token_to_file(Path(secrets_path), token)
    os.environ[ENV_VAR_NAME] = token


def resolve_api_key(secrets_path: Path = DEFAULT_SECRETS_PATH) -> str:
    """Devuelve la API key a usar y deja ANTHROPIC_API_KEY seteada en el proceso
    (para que extract.py la lea sin cambios). Si tuvo que pedirla por consola,
    la guarda en `secrets_path` para las próximas ejecuciones."""
    env_value = os.environ.get(ENV_VAR_NAME)
    if env_value and env_value.strip():
        return env_value.strip()

    secrets_path = Path(secrets_path)
    token = _read_token_from_file(secrets_path)
    if token:
        os.environ[ENV_VAR_NAME] = token
        return token

    token = _prompt_for_token()
    _write_token_to_file(secrets_path, token)
    os.environ[ENV_VAR_NAME] = token
    print(f"API key guardada en '{secrets_path}' para las próximas ejecuciones.")
    return token
