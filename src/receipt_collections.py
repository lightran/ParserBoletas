"""Persistencia de "colecciones": el usuario crea una colección y va subiendo
boletas progresivamente, en distintas sesiones, sin esperar a tenerlas todas. La
extracción por visión no ocurre acá — recién cuando decide generar la rendición,
`web.routes` arma un `Job` normal apuntado a la carpeta de boletas de la colección
y reutiliza el mismo pipeline de siempre (`main.process_all` en adelante). Después
de generar, la colección queda intacta: no se archiva ni se borra, se puede seguir
agregando boletas o volver a generar.

Cada colección es una carpeta bajo `colecciones/` (resuelta con
`paths.writable_path`, para que quede junto al ejecutable empaquetado y persista
entre corridas — ver src/paths.py):

    colecciones/
      <slug>/
        coleccion.json   # nombre visible, fecha de creación, última generación
        boletas/         # las imágenes/PDF subidos
        rendiciones/     # Excel generados (creada recién al generar la primera vez)

El nombre visible (con espacios/acentos) vive en `coleccion.json`; `slug` (nombre
de carpeta) es la versión saneada con `main.sanitize_filename_component` — mismo
criterio que ya usa la app para nombrar el Excel de salida, no uno nuevo.

La lista de boletas NO se guarda en `coleccion.json` (a pesar de que una versión
anterior de este diseño lo proponía): se deriva siempre en vivo listando
`boletas/`, para que nunca pueda quedar desincronizada de lo que realmente hay en
disco (ej. si el proceso se interrumpe a mitad de una escritura de metadata).

`coleccion.json` lleva un campo `version` (`CURRENT_METADATA_VERSION`) desde que se
agregó el import por ZIP (ver `import_collection_from_zip` más abajo) — mismo
esquema para colecciones creadas a mano o importadas, no hay dos formatos.

## Import desde ZIP (`import_collection_from_zip`)

Formato de intercambio pensado para una herramienta externa (ej. una app de
celular que captura boletas y exporta la colección) — **no es el mismo esquema
que el `coleccion.json` local**, porque acá sí hace falta declarar qué boletas
debería tener el paquete, para poder detectar un ZIP incompleto/corrupto antes de
tocar nada en disco:

    <NombreColeccion>.zip
    ├── coleccion.json     # {"version": 1, "name": "...", "receipts": ["a.jpg", ...], "created_at": "..." (opcional)}
    └── boletas/
        ├── a.jpg
        └── ...

Al importar, se valida todo (estructura, versión soportada, que cada boleta de
`receipts` exista de verdad en `boletas/`, sin archivos sin declarar, sin rutas
inseguras) ANTES de tocar cualquier colección existente, y recién entonces se
reconstruye la colección en el disco con el mismo formato que usan las
colecciones locales (mismo `coleccion.json` con `version`/`name`/`created_at`/
`last_generated_at`, sin el campo `receipts` — se sigue derivando del disco,
igual que siempre).
"""

from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, List, Optional, Union

import paths
from main import SUPPORTED_SUFFIXES, sanitize_filename_component, sanitize_receipt_name

COLLECTIONS_DIRNAME = "colecciones"
METADATA_FILENAME = "coleccion.json"
BOLETAS_DIRNAME = "boletas"
RENDICIONES_DIRNAME = "rendiciones"

# Carpeta reservada para armar una colección importada antes del swap atómico
# (ver import_collection_from_zip). Vive DENTRO de colecciones/ a propósito —
# mismo volumen que el destino final, para que el rename() de intercambio sea
# atómico incluso en el .exe empaquetado. list_collections() no la confunde con
# una colección real porque no tiene coleccion.json en ese nivel (solo sus
# subcarpetas de staging lo tienen, y esas no las recorre iterdir()).
_IMPORT_STAGING_DIRNAME = "_import_staging"

# Nombres de archivo que algunas herramientas (macOS, Windows) dejan sueltas en
# carpetas comprimidas sin que el usuario lo pida — no cuentan como "archivo
# inesperado" al validar que boletas/ coincida con la metadata.
_IGNORED_EXTRA_FILENAMES = {".ds_store", "thumbs.db"}

CURRENT_METADATA_VERSION = 1
SUPPORTED_METADATA_VERSIONS = {1}


class InvalidCollectionArchiveError(ValueError):
    """El ZIP no tiene la estructura/metadata esperada para importarse como
    colección (corrupto, incompleto, versión no soportada, ruta insegura, etc.)."""


class CollectionNotFoundError(LookupError):
    """No existe una colección con ese slug."""


class CollectionAlreadyExistsError(ValueError):
    """Ya existe una colección cuyo nombre sanea al mismo slug."""


@dataclass
class CollectionSummary:
    slug: str
    name: str
    created_at: str
    last_generated_at: Optional[str]
    n_receipts: int


def _collections_root() -> Path:
    return paths.writable_path(COLLECTIONS_DIRNAME)


def _collection_dir(slug: str) -> Path:
    return _collections_root() / slug


def _metadata_path(slug: str) -> Path:
    return _collection_dir(slug) / METADATA_FILENAME


def boletas_dir(slug: str) -> Path:
    return _collection_dir(slug) / BOLETAS_DIRNAME


def rendiciones_dir(slug: str) -> Path:
    return _collection_dir(slug) / RENDICIONES_DIRNAME


def slugify(name: str) -> str:
    return sanitize_filename_component(name)


def _read_metadata(slug: str) -> dict:
    path = _metadata_path(slug)
    if not path.exists():
        raise CollectionNotFoundError(slug)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_metadata(slug: str, data: dict) -> None:
    with open(_metadata_path(slug), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def create_collection(name: str) -> CollectionSummary:
    """Crea la carpeta + metadata de una colección nueva. `name` es el nombre
    visible tal como lo escribió el usuario (con espacios/acentos); el nombre de
    carpeta se deriva saneado. Lanza `ValueError` si el nombre sanea a vacío o al
    slug reservado de staging de import, o `CollectionAlreadyExistsError` si ya
    existe una colección con ese slug."""
    name = name.strip()
    if not name:
        raise ValueError("El nombre de la colección no puede quedar vacío.")
    slug = slugify(name)
    if not slug or slug == _IMPORT_STAGING_DIRNAME:
        raise ValueError("El nombre de la colección no puede quedar vacío después de sanearlo.")
    if _collection_dir(slug).exists():
        raise CollectionAlreadyExistsError(slug)

    boletas_dir(slug).mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).isoformat()
    _write_metadata(
        slug,
        {
            "version": CURRENT_METADATA_VERSION,
            "name": name,
            "created_at": created_at,
            "last_generated_at": None,
        },
    )
    return get_collection(slug)


def get_collection(slug: str) -> CollectionSummary:
    data = _read_metadata(slug)
    return CollectionSummary(
        slug=slug,
        name=data["name"],
        created_at=data["created_at"],
        last_generated_at=data.get("last_generated_at"),
        n_receipts=len(list_receipts(slug)),
    )


def list_collections() -> List[CollectionSummary]:
    root = _collections_root()
    if not root.exists():
        return []
    return [
        get_collection(entry.name)
        for entry in sorted(root.iterdir())
        if entry.is_dir() and (entry / METADATA_FILENAME).exists()
    ]


def list_receipts(slug: str) -> List[Path]:
    directory = boletas_dir(slug)
    if not directory.exists():
        raise CollectionNotFoundError(slug)
    return sorted(p for p in directory.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)


def add_receipt(slug: str, filename: str, content: bytes) -> Path:
    directory = boletas_dir(slug)
    if not directory.exists():
        raise CollectionNotFoundError(slug)
    dest = directory / Path(filename).name
    dest.write_bytes(content)
    return dest


def remove_receipt(slug: str, filename: str) -> None:
    (boletas_dir(slug) / Path(filename).name).unlink(missing_ok=True)


def replace_receipt(slug: str, old_filename: str, new_filename: str, content: bytes) -> Path:
    """Elimina `old_filename` y sube `new_filename` con `content` en su lugar."""
    remove_receipt(slug, old_filename)
    return add_receipt(slug, new_filename, content)


def rename_receipt(slug: str, filename: str, new_name: str) -> Path:
    """Renombra la parte descriptiva de una boleta ya subida (la extensión se
    preserva siempre — nunca se deja que el usuario cambie el tipo de archivo sin
    querer). Pensado para que el nombre refleje mejor lo que va a terminar en la
    columna Comments del Excel, que es justo este nombre de archivo sin extensión
    (ver main.py::build_comments). Lanza `CollectionNotFoundError` si la colección
    no existe, `FileNotFoundError` si `filename` no existe, `ValueError` si el
    nuevo nombre sanea a vacío, y `FileExistsError` si ya hay otra boleta con el
    nombre resultante."""
    directory = boletas_dir(slug)
    if not directory.exists():
        raise CollectionNotFoundError(slug)

    old_path = directory / Path(filename).name
    if not old_path.exists():
        raise FileNotFoundError(filename)

    sanitized = sanitize_receipt_name(new_name)
    if not sanitized:
        raise ValueError("El nombre no puede quedar vacío después de sanearlo.")

    new_path = old_path.with_stem(sanitized)
    if new_path != old_path and new_path.exists():
        raise FileExistsError(new_path.name)

    old_path.rename(new_path)
    return new_path


def mark_generated(slug: str) -> None:
    data = _read_metadata(slug)
    data["last_generated_at"] = datetime.now(timezone.utc).isoformat()
    _write_metadata(slug, data)


# --- Import desde ZIP -----------------------------------------------------------


def _staging_root() -> Path:
    root = _collections_root() / _IMPORT_STAGING_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extrae `zf` en `dest`, entrada por entrada, rechazando cualquiera que
    intente escribir fuera de `dest` (zip-slip: "..", rutas absolutas, letra de
    unidad). Nunca usa `ZipFile.extractall()` — esa API no protege contra esto."""
    dest = dest.resolve()
    for member in zf.infolist():
        if member.is_dir():
            continue
        target = (dest / member.filename).resolve()
        if target != dest and dest not in target.parents:
            raise InvalidCollectionArchiveError(
                f"El ZIP contiene una ruta insegura: '{member.filename}'."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def _load_manifest(staging_dir: Path) -> dict:
    manifest_path = staging_dir / METADATA_FILENAME
    if not manifest_path.exists():
        raise InvalidCollectionArchiveError(
            f"El ZIP no tiene '{METADATA_FILENAME}' en la raíz."
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidCollectionArchiveError(f"'{METADATA_FILENAME}' no es JSON válido: {exc}")
    if not isinstance(manifest, dict):
        raise InvalidCollectionArchiveError(f"'{METADATA_FILENAME}' debe ser un objeto JSON.")

    version = manifest.get("version")
    if version not in SUPPORTED_METADATA_VERSIONS:
        raise InvalidCollectionArchiveError(
            f"Versión de formato no soportada: {version!r} "
            f"(soportadas: {sorted(SUPPORTED_METADATA_VERSIONS)})."
        )

    name = manifest.get("name")
    if not isinstance(name, str) or not name.strip():
        raise InvalidCollectionArchiveError(f"'name' falta o está vacío en {METADATA_FILENAME}.")

    receipts = manifest.get("receipts")
    if not isinstance(receipts, list) or not all(isinstance(r, str) and r for r in receipts):
        raise InvalidCollectionArchiveError(
            f"'receipts' debe ser una lista de nombres de archivo en {METADATA_FILENAME}."
        )
    for receipt in receipts:
        if Path(receipt).name != receipt:
            raise InvalidCollectionArchiveError(f"Nombre de boleta inválido en la metadata: {receipt!r}")
        if Path(receipt).suffix.lower() not in SUPPORTED_SUFFIXES:
            raise InvalidCollectionArchiveError(f"Extensión no soportada en la metadata: {receipt!r}")

    return manifest


def _validate_boletas_dir(staging_dir: Path, receipts: List[str]) -> None:
    boletas_path = staging_dir / BOLETAS_DIRNAME
    if not boletas_path.is_dir():
        raise InvalidCollectionArchiveError(f"El ZIP no tiene la carpeta '{BOLETAS_DIRNAME}/'.")

    on_disk = {p.name for p in boletas_path.iterdir() if p.is_file()}
    expected = set(receipts)

    missing = expected - on_disk
    if missing:
        raise InvalidCollectionArchiveError(
            "El ZIP está incompleto, faltan boletas: " + ", ".join(sorted(missing))
        )

    unexpected = {
        name for name in (on_disk - expected) if name.lower() not in _IGNORED_EXTRA_FILENAMES
    }
    if unexpected:
        raise InvalidCollectionArchiveError(
            "El ZIP tiene archivos en boletas/ no declarados en la metadata: "
            + ", ".join(sorted(unexpected))
        )


def import_collection_from_zip(
    zip_source: Union[Path, str, BinaryIO], *, replace_existing: bool = False
) -> CollectionSummary:
    """Importa (crea o reemplaza por completo) una colección desde un ZIP con el
    formato de intercambio documentado arriba en el docstring del módulo.

    Valida exhaustivamente ANTES de tocar cualquier colección existente. Si ya
    existe una colección con el mismo nombre y `replace_existing` es `False`,
    levanta `CollectionAlreadyExistsError` sin cambiar nada — el caller (la capa
    web) debe pedir confirmación explícita al usuario y reintentar con
    `replace_existing=True`.

    El reemplazo es atómico: arma la colección completa en una carpeta de
    staging dentro de `colecciones/` (mismo volumen que el destino final, para
    que el intercambio sea un `rename()` — atómico en el mismo filesystem, a
    diferencia de copiar entre volúmenes distintos) y recién al final la
    intercambia por la definitiva. Si el ZIP viene corrupto, incompleto, o la
    validación falla en cualquier punto, la colección existente (si había)
    queda intacta — nunca se toca hasta que todo lo demás ya pasó.
    """
    staging_dir = _staging_root() / uuid.uuid4().hex
    staging_dir.mkdir(parents=True)
    try:
        try:
            with zipfile.ZipFile(zip_source) as zf:
                _safe_extract(zf, staging_dir)
        except zipfile.BadZipFile as exc:
            raise InvalidCollectionArchiveError(f"El ZIP está corrupto o no es un .zip válido: {exc}")

        manifest = _load_manifest(staging_dir)
        _validate_boletas_dir(staging_dir, manifest["receipts"])

        name = manifest["name"].strip()
        slug = slugify(name)
        if not slug or slug == _IMPORT_STAGING_DIRNAME:
            raise InvalidCollectionArchiveError(
                "El nombre de la colección no puede quedar vacío después de sanearlo."
            )

        final_dir = _collection_dir(slug)
        already_existed = final_dir.exists()
        if already_existed and not replace_existing:
            raise CollectionAlreadyExistsError(slug)

        # Reescribe la metadata al esquema local estándar — igual que una
        # colección creada a mano, sin "receipts" (se deriva siempre del disco).
        created_at = manifest.get("created_at") or datetime.now(timezone.utc).isoformat()
        (staging_dir / METADATA_FILENAME).write_text(
            json.dumps(
                {
                    "version": CURRENT_METADATA_VERSION,
                    "name": name,
                    "created_at": created_at,
                    "last_generated_at": None,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (staging_dir / RENDICIONES_DIRNAME).mkdir(exist_ok=True)

        backup_dir = None
        if already_existed:
            backup_dir = final_dir.with_name(f"{final_dir.name}.import-backup-{uuid.uuid4().hex}")
            final_dir.rename(backup_dir)
        try:
            staging_dir.rename(final_dir)
        except Exception:
            if backup_dir is not None and backup_dir.exists():
                if final_dir.exists():
                    shutil.rmtree(final_dir, ignore_errors=True)
                backup_dir.rename(final_dir)
            raise
        else:
            if backup_dir is not None:
                shutil.rmtree(backup_dir, ignore_errors=True)
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)

    return get_collection(slug)
