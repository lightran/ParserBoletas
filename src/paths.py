"""Resolución de rutas para que la interfaz web funcione igual corriendo desde
código fuente que empaquetada como ejecutable one-file de PyInstaller.

Dos categorías de recursos, con reglas de resolución distintas:

- **Solo lectura, bundleados** (`resource_path`): plantillas HTML/CSS/JS del
  frontend, la plantilla Excel de rendición, el `config.yaml` de fábrica. En un
  one-file de PyInstaller viven extraídos en una carpeta temporal
  (`sys._MEIPASS`) que se borra al cerrar el programa — nunca hay que escribir ahí.
  En desarrollo (`sys._MEIPASS` no existe) se resuelven relativos a la raíz del
  repo, para que el mismo código funcione en ambos casos.
- **Escribibles y persistentes** (`writable_path`): `config.yaml` (editable por
  el usuario), `secrets.yaml` (token de Anthropic), y cualquier archivo que la
  app necesite recordar entre corridas. Empaquetado, viven junto al `.exe`
  (`sys.executable`), no en `_MEIPASS`. En desarrollo, en la raíz del repo.

Solo usado por la capa de interfaz web (`app.py`, `src/web/routes.py`) — la CLI
(`src/main.py`) y los módulos de negocio (`excel_writer.py`, `api_key.py`, etc.)
no cambian: siguen recibiendo objetos `Path` ya resueltos, sin saber si el
proceso está empaquetado o no.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """True cuando el proceso corre como ejecutable de PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def resource_path(relative: str) -> Path:
    """Ruta de solo lectura, empaquetada dentro del ejecutable.

    `relative` usa "/" y es relativa a la raíz del repo (ej.
    "plantilla/Form - Chile Expense Report - Peru Travel Junio 2026.xlsx",
    "src/web/templates") — el `.spec` bundlea los `datas` respetando esa misma
    estructura relativa, así que la ruta resultante es idéntica empaquetado o no.
    """
    base = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    return base / relative


def writable_path(relative: str) -> Path:
    """Ruta escribible y persistente entre corridas.

    Empaquetado: junto al `.exe` (`sys.executable`). En desarrollo: raíz del
    repo. Nunca apunta a `_MEIPASS` (esa carpeta es temporal y se borra al
    cerrar el programa).
    """
    base = Path(sys.executable).resolve().parent if is_frozen() else PROJECT_ROOT
    return base / relative
