"""Punto de entrada único de la interfaz web.

Uso (desde código fuente):
    python app.py

Levanta un servidor local (un solo proceso, sirve la página y corre el pipeline)
y abre el navegador automáticamente. Reutiliza el mismo pipeline de negocio que la
CLI (`src/main.py`) — esta es solo la capa de interfaz, ver `src/web/routes.py`.
Rutas resueltas vía `src/paths.py` (bundle de solo lectura vs. junto al ejecutable
para lo escribible) — funciona igual corriendo desde código fuente que empaquetado
como .exe de PyInstaller (ver `app.spec`/`build.bat`), sin importar desde qué
directorio se invoque.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import certifi  # noqa: E402
import uvicorn  # noqa: E402

from main import _ensure_utf8_console  # noqa: E402
from web.routes import app  # noqa: E402

# Refuerzo de certificados SSL para las llamadas HTTPS a la API de Claude: el hook
# de PyInstaller para certifi ya bundlea cacert.pem, pero setear esta env var acá
# cubre igual cualquier librería que confíe en SSL_CERT_FILE en vez de resolver el
# bundle de certifi por su cuenta — sin esto, una máquina limpia sin certificados
# de sistema puede fallar la validación SSL aunque el resto del .exe funcione bien.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

HOST = os.environ.get("PARSERBOLETAS_HOST", "127.0.0.1")
PREFERRED_PORT = int(os.environ.get("PARSERBOLETAS_PORT", "8000"))


def _resolve_port(host: str, preferred: int) -> int:
    """Usa `preferred` si está libre; si no (otra instancia corriendo, puerto
    ocupado por otra app), le pide uno libre al sistema operativo en vez de
    fallar al arrancar."""
    for candidate in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, candidate))
                return s.getsockname()[1]
        except OSError:
            continue
    raise RuntimeError(f"No se encontró un puerto disponible en {host}.")


def _open_browser(port: int) -> None:
    webbrowser.open(f"http://{HOST}:{port}")


def main() -> None:
    _ensure_utf8_console()
    port = _resolve_port(HOST, PREFERRED_PORT)
    if port != PREFERRED_PORT:
        print(f"Puerto {PREFERRED_PORT} ocupado, usando {port} en su lugar.")
    print(f"ParserBoletas: http://{HOST}:{port}  (Ctrl+C para detener)")
    threading.Timer(1.0, _open_browser, args=(port,)).start()
    uvicorn.run(app, host=HOST, port=port, log_level="info")


if __name__ == "__main__":
    main()
