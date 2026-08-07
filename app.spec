# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec de ParserBoletas — entrypoint: app.py (servidor web local).

Uso normal (one-file, modo por defecto):
    pyinstaller app.spec --noconfirm --clean

Modo one-folder (arranca más rápido; reparte el .exe + archivos de soporte en una
carpeta en vez de un solo .exe autoextraíble) sin tocar este archivo:
    set PARSERBOLETAS_ONEDIR=1
    pyinstaller app.spec --noconfirm --clean

Generado originalmente con `pyi-makespec --onefile --console app.py` y editado a
mano para: (1) bundlear los recursos de solo lectura que la app lee desde disco
(plantillas/estáticos del frontend, la plantilla Excel, config.yaml de fábrica —
ver src/paths.py::resource_path para cómo se resuelven en runtime), y (2) declarar
los hiddenimports que el análisis estático de PyInstaller no detecta solo.
"""

import os

ONEDIR = bool(os.environ.get("PARSERBOLETAS_ONEDIR"))

# Los destinos dentro del bundle mantienen la MISMA ruta relativa que en el repo
# (ej. "src/web/templates" -> "src/web/templates" dentro de sys._MEIPASS), para
# que resource_path() resuelva idéntico empaquetado o corriendo desde código
# fuente — ver el docstring de src/paths.py.
datas = [
    ("src/web/templates", "src/web/templates"),
    ("src/web/static", "src/web/static"),
    ("plantilla", "plantilla"),
    ("config.yaml", "."),
]

hiddenimports = [
    # python-multipart: starlette lo importa de forma perezosa al parsear
    # multipart/form-data (la subida de boletas) — el análisis estático de
    # PyInstaller no lo encuentra solo. La versión instalada (0.0.32) expone el
    # paquete bajo los dos nombres; se agregan ambos por las dudas.
    "multipart",
    "python_multipart",
    # PyMuPDF: import directo y estático en preprocess.py, así que debería
    # detectarse solo, pero no tiene hook dedicado en pyinstaller-hooks-contrib
    # (a diferencia de cv2/uvicorn/pydantic) — se agrega como respaldo barato.
    "fitz",
    # Parser JSON compilado (extensión Rust) que usa el SDK de Anthropic.
    "jiter",
]
# uvicorn, cv2, pydantic, anyio y certifi YA tienen hooks oficiales en
# pyinstaller-hooks-contrib (verificado localmente: hook-uvicorn.py hace
# collect_submodules('uvicorn'), hook-certifi.py bundlea cacert.pem vía
# collect_data_files, hook-cv2.py y hook-pydantic.py resuelven sus propios
# imports dinámicos) — no hace falta declararlos acá. requirements-build.txt
# fija pyinstaller-hooks-contrib como dependencia de build para que estos hooks
# estén disponibles.

a = Analysis(
    ["app.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if ONEDIR:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="ParserBoletas",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=True,
    )
    COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="ParserBoletas",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="ParserBoletas",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        # Ventana de consola visible con la URL y los logs — cerrarla detiene el
        # servidor. Es la opción más simple y transparente para el usuario final
        # (alternativa: console=False + windowed, pero entonces hay que resolver
        # aparte cómo mostrar errores de arranque, ej. si el puerto está ocupado).
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
