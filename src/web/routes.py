"""Interfaz web del pipeline: sirve la página única y expone los mismos pasos que
hoy corre `main.run()` por consola, como endpoints HTTP consumidos por `static/app.js`.

No reescribe lógica de negocio — cada endpoint es una fachada delgada sobre
`main.process_all`, `main.detect_fx_requirements`, `complementary_info.CurrencyConversion`,
`excel_writer.write_expense_report` y `audit_writer.write_audit_report`, los mismos
que usa la CLI. El único estado nuevo es `web.state.JobStore` (una sesión en memoria
por "job": boletas subidas + resultados intermedios), necesario porque el flujo web
está partido en varias llamadas (subir -> parsear -> generar) en vez de una sola
corrida bloqueante de consola.
"""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import api_key  # noqa: E402
import audit_writer  # noqa: E402
import complementary_info  # noqa: E402
import cost  # noqa: E402
import excel_writer  # noqa: E402
import main  # noqa: E402
import paths  # noqa: E402

from web.state import Job, JobStore  # noqa: E402

# Plantillas/estáticos son de solo lectura y viven bundleados (ver src/paths.py):
# empaquetado, dentro de sys._MEIPASS; en desarrollo, en el árbol del repo.
TEMPLATES_DIR = paths.resource_path("src/web/templates")
STATIC_DIR = paths.resource_path("src/web/static")
BUNDLED_CONFIG_PATH = paths.resource_path("config.yaml")

# config.yaml/secrets.yaml son escribibles y deben sobrevivir entre corridas —
# junto al .exe cuando está empaquetado, no en la carpeta temporal de PyInstaller
# (ver paths.writable_path). Los env vars siguen teniendo prioridad, igual que antes.
CONFIG_PATH = Path(os.environ["PARSERBOLETAS_CONFIG"]) if "PARSERBOLETAS_CONFIG" in os.environ else paths.writable_path("config.yaml")
SECRETS_PATH = Path(os.environ["PARSERBOLETAS_SECRETS"]) if "PARSERBOLETAS_SECRETS" in os.environ else paths.writable_path("secrets.yaml")

store = JobStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    store.close()


app = FastAPI(title="ParserBoletas", lifespan=lifespan)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _ensure_default_config() -> None:
    """Primera corrida: si no hay `config.yaml` en la ubicación escribible (ej. un
    .exe suelto en una carpeta vacía), lo siembra desde el que viene bundleado —
    así el usuario puede editarlo después sin perder los cambios en la próxima
    corrida, y sin depender de que exista algo más además del ejecutable."""
    if not CONFIG_PATH.exists() and BUNDLED_CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BUNDLED_CONFIG_PATH, CONFIG_PATH)


_ensure_default_config()


def _config() -> dict:
    config = main.load_config(CONFIG_PATH)
    # La plantilla Excel es de solo lectura y va bundleada; se resuelve contra
    # resource_path() para que la ruta relativa de config.yaml ("plantilla/...")
    # siga siendo portable y editable a mano, empaquetado o no.
    excel_cfg = config.get("excel", {})
    template_path = excel_cfg.get("template_path")
    if template_path and not Path(template_path).is_absolute():
        excel_cfg["template_path"] = str(paths.resource_path(template_path))
    return config


def _get_job(job_id: str) -> Job:
    try:
        return store.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Sesión no encontrada. Recarga la página.")


def _usage_payload(n_processed: int, usage: "cost.TokenUsage", config: dict) -> dict:
    pricing_cfg = config.get("pricing", {})
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
        "total_tokens": usage.total_tokens,
        "estimated_cost_usd": round(cost.estimate_cost_usd(usage, pricing_cfg), 4),
        "summary_text": cost.format_summary(n_processed, usage, pricing_cfg),
    }


# --- Pydantic models ---------------------------------------------------------


class ApiKeyRequest(BaseModel):
    api_key: str


class ConversionInput(BaseModel):
    currency: str
    filename: str
    usd_charged: float = Field(gt=0)


class GenerateRequest(BaseModel):
    description: str = ""
    usd_fx: Optional[float] = Field(default=None, gt=0)
    conversions: List[ConversionInput] = Field(default_factory=list)


# --- Página -------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


# --- Configuración / API key ---------------------------------------------------


@app.get("/api/config-status")
def config_status():
    return {"has_api_key": api_key.has_saved_key(SECRETS_PATH)}


@app.post("/api/config/api-key")
def set_api_key(payload: ApiKeyRequest):
    try:
        api_key.save_api_key(payload.api_key, SECRETS_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"has_api_key": True}


# --- Jobs -----------------------------------------------------------------------


@app.post("/api/jobs")
def create_job():
    job = store.create()
    return {"job_id": job.id}


@app.post("/api/jobs/{job_id}/receipts")
async def upload_receipts(job_id: str, files: List[UploadFile] = File(...)):
    job = _get_job(job_id)
    saved: List[str] = []
    rejected: List[str] = []

    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in main.SUPPORTED_SUFFIXES:
            rejected.append(upload.filename or "")
            continue
        dest = job.upload_dir / Path(upload.filename).name
        with dest.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        if dest not in job.files:
            job.files.append(dest)
        saved.append(dest.name)

    job.files.sort()
    # Un nuevo upload invalida el parseo anterior (hay boletas nuevas sin procesar).
    _reset_parse_state(job)

    return {"files": [p.name for p in job.files], "rejected": rejected}


@app.delete("/api/jobs/{job_id}/receipts/{filename}")
def remove_receipt(job_id: str, filename: str):
    job = _get_job(job_id)
    target = job.upload_dir / filename
    job.files = [p for p in job.files if p.name != filename]
    target.unlink(missing_ok=True)
    _reset_parse_state(job)
    return {"files": [p.name for p in job.files]}


def _reset_parse_state(job: Job) -> None:
    job.summary = None
    job.requirements = None
    job.parse_payload = None
    job.progress = {"status": "idle", "total": 0, "done": 0, "current_file": None, "error": None}


def _run_parse(job: Job, config: dict) -> None:
    """Corre en un hilo de fondo (agendado por BackgroundTasks) para que la página
    pueda hacer polling del avance vía GET .../parse/status en vez de bloquearse
    esperando la respuesta de una sola llamada larga."""
    counter = {"done": 0}

    def on_progress(file_path: Path) -> None:
        # `main.process_all` llama a este hook ANTES de procesar cada archivo: al
        # dispararse para el archivo N, los N-1 anteriores ya terminaron.
        job.progress["current_file"] = file_path.name
        job.progress["done"] = counter["done"]
        counter["done"] += 1

    try:
        summary = main.process_all(job.files, config, on_progress=on_progress)
        requirements = main.detect_fx_requirements(summary.rows_to_write)
        job.summary = summary
        job.requirements = requirements

        candidates_by_currency: Dict[str, list] = {
            code: [
                {
                    "filename": row.source_file,
                    "amount": float(row.amount),
                    "date": row.date.isoformat() if row.date else None,
                }
                for row in summary.rows_to_write
                if row.currency == code
            ]
            for code in requirements.conversion_currencies
        }
        job.parse_payload = {
            "n_total": summary.n_total,
            "n_ok": summary.n_ok,
            "n_review": len(summary.review_cases),
            "needs_usd_fx": requirements.has_usd or bool(requirements.conversion_currencies),
            "conversion_currencies": requirements.conversion_currencies,
            "candidates_by_currency": candidates_by_currency,
            "usage": _usage_payload(summary.n_total, summary.total_usage, config),
        }
        job.progress["done"] = job.progress["total"]
        job.progress["current_file"] = None
        job.progress["status"] = "done"
    except Exception as exc:
        # Un hilo de fondo que revienta sin capturar no tiene forma de avisarle al
        # cliente (la respuesta HTTP de POST /parse ya se mandó) — se guarda acá
        # para que el polling lo muestre, en vez de perderse en el log del server.
        job.progress["status"] = "error"
        job.progress["error"] = str(exc)


@app.post("/api/jobs/{job_id}/parse")
def parse_job(job_id: str, background_tasks: BackgroundTasks):
    job = _get_job(job_id)
    if not job.files:
        raise HTTPException(status_code=400, detail="No hay boletas cargadas.")
    if not api_key.has_saved_key(SECRETS_PATH):
        raise HTTPException(
            status_code=400, detail="Falta configurar la API key de Anthropic."
        )
    if job.progress["status"] == "running":
        raise HTTPException(status_code=409, detail="Ya hay un procesamiento en curso.")
    api_key.resolve_api_key(SECRETS_PATH)  # deja ANTHROPIC_API_KEY seteada en el proceso

    config = _config()
    _reset_parse_state(job)
    job.progress["status"] = "running"
    job.progress["total"] = len(job.files)

    background_tasks.add_task(_run_parse, job, config)
    return {"status": "started", "total": len(job.files)}


@app.get("/api/jobs/{job_id}/parse/status")
def parse_status(job_id: str):
    job = _get_job(job_id)
    payload = dict(job.progress)
    if job.progress["status"] == "done" and job.parse_payload:
        payload.update(job.parse_payload)
    return payload


def _missing_requirements(job: Job, payload: GenerateRequest) -> List[str]:
    return main.compute_missing_requirements(
        n_files=len(job.files),
        parsed=job.summary is not None,
        description=payload.description,
        requirements=job.requirements,
        usd_fx=payload.usd_fx,
        submitted_conversion_currencies=[c.currency for c in payload.conversions],
    )


@app.post("/api/jobs/{job_id}/validate")
def validate_job(job_id: str, payload: GenerateRequest):
    job = _get_job(job_id)
    missing = _missing_requirements(job, payload)
    return {"ready": not missing, "missing": missing}


@app.post("/api/jobs/{job_id}/generate")
def generate_job(job_id: str, payload: GenerateRequest):
    job = _get_job(job_id)
    missing = _missing_requirements(job, payload)
    if missing:
        raise HTTPException(status_code=400, detail="; ".join(missing))

    config = _config()
    summary = job.summary
    rows = summary.rows_to_write

    fx_rates: Dict[str, float] = {}
    conversions: List[complementary_info.CurrencyConversion] = []

    if job.requirements.has_usd:
        fx_rates["USD"] = payload.usd_fx

    usd_to_clp = fx_rates.get("USD", payload.usd_fx)
    for item in payload.conversions:
        row = next(
            (r for r in rows if r.source_file == item.filename and r.currency == item.currency),
            None,
        )
        if row is None:
            raise HTTPException(
                status_code=400,
                detail=f"No se encontró la boleta '{item.filename}' en {item.currency}.",
            )
        conversion = complementary_info.CurrencyConversion(
            currency=item.currency,
            file_path=row.file_path,
            dato_a=float(row.amount),
            dato_b=item.usd_charged,
            dato_c=usd_to_clp,
        )
        fx_rates[item.currency] = conversion.fx_step2
        conversions.append(conversion)

    for row in rows:
        row.fx = fx_rates.get(row.currency, excel_writer.DEFAULT_FX)

    description = main.sanitize_filename_component(payload.description)
    report_path = job.output_dir / f"Expense_Report_{description}.xlsx"
    audit_path = job.output_dir / "auditoria.xlsx"

    excel_writer.write_expense_report(rows, config, report_path, conversions=conversions)
    audit_result_path = audit_writer.write_audit_report(summary.review_cases, config, audit_path)

    job.report_path = report_path
    job.audit_path = audit_result_path

    return {
        "report_url": f"/api/jobs/{job_id}/download/report",
        "audit_url": f"/api/jobs/{job_id}/download/audit" if audit_result_path else None,
        "summary": {
            "n_ok": summary.n_ok,
            "n_review": len(summary.review_cases),
            "n_total": summary.n_total,
        },
        "usage": _usage_payload(summary.n_total, summary.total_usage, config),
    }


@app.get("/api/jobs/{job_id}/download/{kind}")
def download(job_id: str, kind: str):
    job = _get_job(job_id)
    path = {"report": job.report_path, "audit": job.audit_path}.get(kind)
    if path is None or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Archivo no disponible.")
    return FileResponse(
        path,
        filename=Path(path).name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
