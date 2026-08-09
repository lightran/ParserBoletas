"""Estado en memoria de las sesiones ("jobs") de la interfaz web.

Un job agrupa las boletas subidas y los resultados intermedios de una corrida:
cargar -> parsear -> generar. Vive solo en la memoria del proceso — esta es una
herramienta local de un solo usuario, no hace falta persistencia entre reinicios
ni entre procesos.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import main  # noqa: E402


def _initial_progress() -> dict:
    return {"status": "idle", "total": 0, "done": 0, "current_file": None, "error": None}


@dataclass
class Job:
    id: str
    upload_dir: Path
    output_dir: Path
    files: List[Path] = field(default_factory=list)
    summary: Optional["main.ProcessingSummary"] = None
    requirements: Optional["main.FxRequirements"] = None
    report_path: Optional[Path] = None
    audit_path: Optional[Path] = None
    # Avance del paso de parseo, corrido en un hilo de fondo para que la página
    # pueda hacer polling del progreso ("status" en idle | running | done | error).
    progress: dict = field(default_factory=_initial_progress)
    parse_payload: Optional[dict] = None
    # Si este job se creó para generar la rendición de una colección (ver
    # web.routes::create_generate_job), el slug de esa colección — para poder
    # avisarle a receipt_collections que se generó (metadata.last_generated_at) al
    # terminar POST /generate. None para el flujo de carga suelta de siempre.
    collection_slug: Optional[str] = None


class JobStore:
    """Guarda los jobs activos y sus directorios temporales de trabajo."""

    def __init__(self, base_dir: Optional[Path] = None):
        self._base_dir = Path(base_dir) if base_dir else Path(
            tempfile.mkdtemp(prefix="parserboletas-web-")
        )
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(
        self,
        upload_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        collection_slug: Optional[str] = None,
    ) -> Job:
        """Crea un job. Sin argumentos: flujo de carga suelta de siempre (dos
        directorios temporales vacíos, borrados por `close()`). Con `upload_dir`/
        `output_dir` (ver web.routes::create_generate_job, que los apunta a la
        carpeta persistente de una colección): no crea el upload_dir —debe traer
        boletas ya subidas—, solo lo escanea; el output_dir sí se crea si falta,
        y vive fuera de `self._base_dir` así que `close()` no lo toca."""
        job_id = uuid.uuid4().hex
        job_dir = self._base_dir / job_id

        if upload_dir is None:
            upload_dir = job_dir / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
        if output_dir is None:
            output_dir = job_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        files = sorted(
            p for p in upload_dir.iterdir() if p.suffix.lower() in main.SUPPORTED_SUFFIXES
        ) if upload_dir.exists() else []

        job = Job(
            id=job_id,
            upload_dir=upload_dir,
            output_dir=output_dir,
            files=files,
            collection_slug=collection_slug,
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def close(self) -> None:
        """Borra todos los directorios temporales de trabajo. Se llama al apagar
        el servidor (ver `web.routes` lifespan)."""
        shutil.rmtree(self._base_dir, ignore_errors=True)
