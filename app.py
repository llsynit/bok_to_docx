# app.py
import os
import shutil
import time
import uuid
import tempfile
import io
import re
import logging
import sys
from pathlib import Path
from typing import Dict, Optional
from types import SimpleNamespace
from urllib.parse import urlparse
from datetime import datetime

import aio_pika
import httpx
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from aiormq.exceptions import AMQPConnectionError
from contextlib import suppress, asynccontextmanager
import asyncio

from bok2docx import convert  # your existing validator
from utils import cleanup_artifacts_once

from config import (
    MODULE_NAME_BOK_TO_DOCX, PORT_BOK_TO_DOCX,
    RABBITMQ_URL,
    WORK_EXCHANGE, RESULTS_EXCHANGE, WORK_ROUTING_KEY, WORK_QUEUE_NAME,
    ARTIFACTS_ROOT, WORKER_BASE_URL, ARTIFACTS_RETENTION_HOURS, ARTIFACTS_CLEAN_INTERVAL_SEC
)

# -----------------------------------------------------------------------------
# Logger
# -----------------------------------------------------------------------------

def make_logger() -> logging.Logger:
    """Logger som skriver til stdout (synlig i docker logs)."""
    logger = logging.getLogger("bok_to_docx")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(h)
    return logger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

logging.getLogger("aio_pika").setLevel(logging.WARNING)
logging.getLogger("aiormq").setLevel(logging.WARNING)


uid = "bok_to_docx"

logger.info(f"Starting {MODULE_NAME_BOK_TO_DOCX} on port {PORT_BOK_TO_DOCX}.....")


# =============================================================================
# FastAPI
# =============================================================================

app = FastAPI(title=MODULE_NAME_BOK_TO_DOCX, version="2.0.0", debug=True)
DOWNLOADS: Dict[str, bytes] = {}


app.state.amqp_enabled = False
app.state.amqp_conn = None
app.state.amqp_ch = None
app.state._amqp_reconnector_task = None  # background task handle
RECONNECT_DELAY_SECONDS = 30

# Serve ephemeral artifacts (no persistent volume!)
app.mount("/artifacts", StaticFiles(directory=str(ARTIFACTS_ROOT)),
          name="artifacts")

# =============================================================================
# Small helpers
# =============================================================================


async def _http_download_to(dst: Path, url: str):
    """Download http(s) or copy file:// to dst"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    u = urlparse(url)
    if u.scheme in ("http", "https"):
        async with httpx.AsyncClient(timeout=120) as http:
            r = await http.get(url)
            r.raise_for_status()
            dst.write_bytes(r.content)
    elif u.scheme == "file":
        src = Path(u.path)
        if not src.exists():
            raise FileNotFoundError(f"file:// source not found: {src}")
        dst.write_bytes(src.read_bytes())
    else:
        raise HTTPException(400, f"Unsupported URI scheme: {u.scheme}")


def _art_uri(job_id: str,  name: str) -> str:
    return f"{WORKER_BASE_URL}/artifacts/{job_id}/{name}"


async def _publish_result(stage: str, job_id: str, status: str, artifacts: Dict, correlation_id: Optional[str]):
    rk = f"job.{job_id}.stage.{stage}.status.{status}"
    payload = {
        "job_id": job_id,
        "stage": stage,
        "status": status,          # "ok" | "fail"
        "artifacts": artifacts,    # URIs (ephemeral here)
        "finished_at": time.time()
    }
    body = __import__("json").dumps(
        payload, ensure_ascii=False).encode("utf-8")
    msg = aio_pika.Message(
        body=body,
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        correlation_id=correlation_id,
        message_id=str(uuid.uuid4()),
    )
    await app.state.results_ex.publish(msg, routing_key=rk)

# =============================================================================
# HTTP API (kept for manual testing)
# =============================================================================


@app.get("/health")
def health():
    return {"status": True, "module": MODULE_NAME_BOK_TO_DOCX}

# TODO: update for relevant conversion

@app.post("/run")
async def run(
    request: Request,
    #file: UploadFile = File(..., description="XHTML fra forrige steg i pipelinen"),
    #input: UploadFile = File(..., description="XHTML fra forrige steg i pipelinen"),
    xhtml: UploadFile = File(..., description="XHTML fra forrige steg i pipelinen"),
    # Felter som controlleren allerede sender (noen er ikke brukt her, men tillates for kompatibilitet):
    mathematics: bool = Form(False),
    science: bool = Form(False),
    grade: Optional[int] = Form(None),
    link_footnotes: bool = Form(False),  # ikke brukt her
    verbose: bool = Form(False),         # ikke brukt her
    toc_levels: Optional[int] = Form(None),  # ikke brukt her
    p_length: Optional[int] = Form(None),    # ikke brukt her
    relocate: bool = Form(True),
    llm: bool = Form(False),
):
    """
    Manual test endpoint — not used by RabbitMQ flow.
    Returns a zip file (validator's original behavior).
    """
    t0 = time.time()
    # Get original filename
    original_name = xhtml.filename or ""
    suffix = Path(xhtml.filename or "").suffix or ".xhtml"
    # Extract production_number from filename (basename without extension)
    production_number = Path(original_name).stem

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", production_number)
    tmp_path = Path(tempfile.gettempdir()) / f"{safe_name}{suffix}"
    with open(tmp_path, "wb") as f:
        f.write(await xhtml.read())

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S%f")
    job_id = f"{production_number}-{timestamp}"

    # Bygg args-objektet (dot-notasjon) slik apply_requirements forventer
    args = SimpleNamespace(
        #file=xhtml_path,
        #input=xhtml_path,
        input=str(tmp_path),
        folders=folders,
        production_number=production_number,
        data=data,
        mathematics=bool(mathematics),
        science=bool(science),
        grade=(int(grade) if grade is not None and str(grade).strip() != "" else None),
        job_id=job_id,
        job_dir=job_dir,
        llm=bool(llm),
        aggressive=bool(False),
        relocate=bool(relocate),
        logger=logger,
    )

    try:
        #status = convert(tmp_path, str(production_number), job_id)
        status = convert(args)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
    logger.info("Validation completed, preparing artifacts...")
    job_dir = ARTIFACTS_ROOT / job_id
    logger.info(f"Job dir: {job_dir}")

    if not os.path.isdir(job_dir):
        logger.warning(
            f"Could not find artifact folder for this job: {job_dir}")
        raise HTTPException(
            500, f"Could not find artifact folder for this job: {job_dir}")

    # Zip the folder to a temp file for download
    zip_base = os.path.join(tempfile.gettempdir(), f"{job_id}")
    # returns path/to/<base>.zip
    zip_path = shutil.make_archive(zip_base, "zip", job_dir)

    headers = {
        "X-Validation-Status": status.get("status"),
        "X-Processing-Time-ms": str(int((time.time() - t0) * 1000)),
    }
    download_name = f"{production_number}-artifacts.zip"
    return FileResponse(zip_path, media_type="application/zip", filename=download_name, headers=headers)


@app.get("/download/{token}")
async def download(token: str):
    data = DOWNLOADS.pop(token, None)
    if data is None:
        return JSONResponse(status_code=404, content={"error": "File not found"})
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename=\"result.zip\"'},
    )

# =============================================================================
# RabbitMQ consumer
# =============================================================================


async def _handle_work_message(m: aio_pika.IncomingMessage):
    """
    Expected message body (JSON) from controller:
    {
      "job_id": "...",
      "production_number": "...",
      "stage": "nordic_to_bok",
      "inputs": { "xhtml": "http://controller:7000/downloads/<prod>/<file>.xhtml" },
      "correlation_id": "job::<id>::nordic_to_bok::1",
      ...
    }
    """
    async with m.process():
        data = __import__("json").loads(m.body.decode("utf-8"))
        job_id = data.get("job_id")
        stage = data.get("stage") or "bok_to_docx"
        inputs = data.get("inputs") or {}
        corr_id = data.get("correlation_id") or m.correlation_id
        production_number = str(data.get("production_number") or "")

        xhtml_uri = inputs.get("xhtml_uri")
        if not (job_id and xhtml_uri and production_number):
            await _publish_result(stage, job_id or "?", "fail",
                                  {"error": "missing job_id/xhtml_uri/production_number"}, corr_id)
            return

        # Workspace (EPHEMERAL)
        job_dir = ARTIFACTS_ROOT / job_id
        # job_dir.mkdir(parents=True, exist_ok=True)
        tmp_xhtml = job_dir / "input.xhtml"

        # 1) Fetch xhtml
        await _http_download_to(tmp_xhtml, xhtml_uri)


        # Bygg args-objektet (dot-notasjon) slik convert forventer
        args = SimpleNamespace(
            #input=xhtml_uri,
            input=tmp_xhtml,
            output=data.get("output", None),
            log_level=data.get("log-level", "INFO"),
            folders=data.get("folders", {}),
            production_number=production_number,
            data=data,
            mathematics=bool(data.get("mathematics", False)),
            science=bool(data.get("science", False)),
            grade=(int(data.get("grade")) if data.get("grade") is not None else None),
            reference_docx=data.get("reference_docx", None),
            pandoc_args=data.get("pandoc_args", []),
            stdout=data.get("stdout", False),
            no_excel=data.get("no_excel", False),
            job_id=job_id,
            job_dir=job_dir,
            llm=bool(data.get("llm", False)),
            toc_levels=data.get("toc_levels", None),
            aggressive=bool(data.get("aggressive", False)),
            relocate=bool(data.get("relocate", True)),
            logger=make_logger(),
        )

        # 2) Run nordic_to_bok
        try:
            #status = convert(str(tmp_xhtml), production_number, job_id)
            status = convert(args)
        except Exception as e:
            # crash → publish fail
            artifacts = {"error": f"{uid} crashed: {e}"}
            await _publish_result(stage, job_id, "fail", artifacts, corr_id)
            try:
                tmp_xhtml.unlink(missing_ok=True)
            except Exception:
                pass
            return
        finally:
            try:
                tmp_xhtml.unlink(missing_ok=True)
            except Exception:
                pass

        if not os.path.isdir(job_dir):
            await _publish_result(stage, job_id, "fail",
                                  {"error": f"Could not find artifact folder for this job: {job_dir}"},
                                  corr_id)
            return
        artifacts = {}
        # Build artifact URIs (use relative names under job_dir)
        # Go through all content of job_dir and create URIs for them ignore images folder
        for path in job_dir.rglob("*"):
            # do not ignore images 20.10.25
            #if path.is_file() and "images" not in str(path):
                # use name of the file as key and add to artifacts dict
            artifacts[str(path.relative_to(job_dir))] = _art_uri(
                job_id, str(path.relative_to(job_dir)))

        # Normalize status to "ok"/"fail"
        if isinstance(status, dict):
            status_value = status.get("status")
        else:
            status_value = "ok" if status else "fail"

        logger.info("Publishing result to controller...")
        logger.info(
            f"[{MODULE_NAME_BOK_TO_DOCX}] job {job_id} stage {stage} completed, status: {status_value}")
        await _publish_result(stage, job_id, status_value, artifacts, corr_id)


async def _amqp_reconnector_loop():
    """
    Optional: background loop to try reconnecting periodically.
    Never raises. Stops when app shuts down.
    """
    while True:
        if app.state.amqp_enabled:
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)
            continue

        ok = await _setup_amqp_once()
        if ok:
            # Connected; loop keeps running in case it drops later.
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)
        else:
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


async def _setup_amqp_once():
    try:
        # AMQP connect
        app.state.amqp_conn = await aio_pika.connect_robust(RABBITMQ_URL)
        ch = await app.state.amqp_conn.channel()
        await ch.set_qos(prefetch_count=1)
        app.state.amqp_ch = ch

        # Exchanges
        app.state.work_ex = await ch.declare_exchange(WORK_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)
        app.state.results_ex = await ch.declare_exchange(RESULTS_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)

        # Queue + bind
        q = await ch.declare_queue(WORK_QUEUE_NAME, durable=True)
        await q.bind(app.state.work_ex, routing_key=WORK_ROUTING_KEY)

        # Start consuming
        await q.consume(_handle_work_message)
        logger.info(
            f"[{MODULE_NAME_BOK_TO_DOCX}] consuming: exchange='{WORK_EXCHANGE}' rk='{WORK_ROUTING_KEY}' queue='{WORK_QUEUE_NAME}'")
        return True
    except (AMQPConnectionError, OSError, ConnectionRefusedError) as e:
        # Log as WARNING (not ERROR) so app continues running
        logger.warning(
            "[%s] AMQP connection failed (%s). Running without RabbitMQ. "
            "HTTP endpoints remain available.",
            MODULE_NAME_BOK_TO_DOCX, repr(e)
        )
        # Ensure disabled state
        app.state.amqp_enabled = False
        app.state.amqp_conn = None
        app.state.amqp_ch = None
        return False


async def _cleanup_loop():
    """
    Periodically clean up old artifacts. Never raises.
    """
    while True:
        try:
            stats = cleanup_artifacts_once(
                ARTIFACTS_ROOT, ARTIFACTS_RETENTION_HOURS, logger)
            logger.debug("Artifacts cleanup stats: %s", stats)
        except Exception as e:
            logger.warning("Artifacts cleanup loop error: %r", e)
        await asyncio.sleep(ARTIFACTS_CLEAN_INTERVAL_SEC)

'''
@app.on_event("startup")
async def on_startup():
    # Try once, but do NOT crash the app if it fails
    ok = await _setup_amqp_once()
    if not ok:
        # Optionally, start a background reconnector
        app.state._amqp_reconnector_task = asyncio.create_task(
            _amqp_reconnector_loop())

    logger.info("Starting artifacts cleanup loop...")
    app.state._cleanup_task = asyncio.create_task(_cleanup_loop())


@app.on_event("shutdown")
async def shutdown():
    # stop cleanup loop
    task = getattr(app.state, "_cleanup_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    # stop amqp reconnector loop (if it was started)
    task = getattr(app.state, "_amqp_reconnector_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    # close AMQP channel/connection if present
    ch = getattr(app.state, "amqp_ch", None)
    if ch:
        with suppress(Exception):
            await ch.close()

    conn = getattr(app.state, "amqp_conn", None)
    if conn:
        with suppress(Exception):
            await conn.close()

'''

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic (tidligere @app.on_event("startup"))
    ok = await _setup_amqp_once()
    if not ok:
        # Eventuell bakgrunnsreconnector
        app.state._amqp_reconnector_task = asyncio.create_task(
            _amqp_reconnector_loop()
        )

    logger.info("Starting artifacts cleanup loop...")
    app.state._cleanup_task = asyncio.create_task(_cleanup_loop())

    try:
        # Her kjører selve appen
        yield
    finally:
        # Shutdown logic (tidligere @app.on_event("shutdown"))

        # Stopp cleanup-loop
        task = getattr(app.state, "_cleanup_task", None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        # Stopp AMQP-reconnector (hvis startet)
        task = getattr(app.state, "_amqp_reconnector_task", None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        # Lukk AMQP-kanal/tilkobling
        ch = getattr(app.state, "amqp_ch", None)
        if ch:
            with suppress(Exception):
                await ch.close()

        conn = getattr(app.state, "amqp_conn", None)
        if conn:
            with suppress(Exception):
                await conn.close()

# Fortell FastAPI at den skal bruke lifespan-handleren
app.router.lifespan_context = lifespan
