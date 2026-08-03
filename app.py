"""Punto de entrada único de la interfaz web.

Uso:
    python app.py

Levanta un servidor local (un solo proceso, sirve la página y corre el pipeline)
y abre el navegador automáticamente. Reutiliza el mismo pipeline de negocio que la
CLI (`src/main.py`) — esta es solo la capa de interfaz, ver `src/web/routes.py`.
Correr desde la raíz del repo (mismo supuesto que la CLI: rutas de `config.yaml`
son relativas al directorio de trabajo).
"""

from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import uvicorn  # noqa: E402

from main import _ensure_utf8_console  # noqa: E402
from web.routes import app  # noqa: E402

HOST = os.environ.get("PARSERBOLETAS_HOST", "127.0.0.1")
PORT = int(os.environ.get("PARSERBOLETAS_PORT", "8000"))


def _open_browser() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}")


def main() -> None:
    _ensure_utf8_console()
    print(f"ParserBoletas: http://{HOST}:{PORT}  (Ctrl+C para detener)")
    threading.Timer(1.0, _open_browser).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
