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
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import paths
from main import SUPPORTED_SUFFIXES, sanitize_filename_component, sanitize_receipt_name

COLLECTIONS_DIRNAME = "colecciones"
METADATA_FILENAME = "coleccion.json"
BOLETAS_DIRNAME = "boletas"
RENDICIONES_DIRNAME = "rendiciones"


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
    carpeta se deriva saneado. Lanza `ValueError` si el nombre sanea a vacío, o
    `CollectionAlreadyExistsError` si ya existe una colección con ese slug."""
    name = name.strip()
    if not name:
        raise ValueError("El nombre de la colección no puede quedar vacío.")
    slug = slugify(name)
    if not slug:
        raise ValueError("El nombre de la colección no puede quedar vacío después de sanearlo.")
    if _collection_dir(slug).exists():
        raise CollectionAlreadyExistsError(slug)

    boletas_dir(slug).mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).isoformat()
    _write_metadata(slug, {"name": name, "created_at": created_at, "last_generated_at": None})
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
