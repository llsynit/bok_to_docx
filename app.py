# app.py — FastAPI app, HTTP endpoints, and lifespan
import asyncio
import io
import logging
import os
import re
import shutil
import tempfile
import time
from contextlib import suppress, asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from bok2docx import convert
from config import Config, logger
from utils import cleanup_artifacts_once, summarize_artifacts
import amqp as mq


logging.getLogger("aio_pika").setLevel(logging.WARNING)
logging.getLogger("aiormq").setLevel(logging.WARNING)

DOWNLOADS: Dict[str, bytes] = {}
logger.info(f"Starting {Config.MODULE_NAME} on port {Config.PORT}.....")


# =============================================================================
# Lifespan
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info(f"[{Config.MODULE_NAME}] Starting up...")

    # Initial RabbitMQ connection attempt (non-blocking)
    ok = await mq.setup_amqp(app.state)
    if ok:
        logger.info(f"[{Config.MODULE_NAME}] Successfully connected to RabbitMQ")
    else:
        logger.warning(
            f"[{Config.MODULE_NAME}] RabbitMQ unavailable at startup. "
            "HTTP endpoints are active. Retrying every 10 s in background."
        )

    # Background tasks
    logger.info("Starting artifacts cleanup loop...")
    app.state._cleanup_task = asyncio.create_task(
        _cleanup_loop()
    )

    logger.info("Starting result republisher...")
    app.state._republish_task = asyncio.create_task(
        mq.republish_pending_results(app.state)
    )

    logger.info("Starting RabbitMQ reconnector loop...")
    app.state._reconnector_task = asyncio.create_task(
        mq.amqp_reconnector_loop(app.state)
    )

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info(f"[{Config.MODULE_NAME}] Shutting down...")

    for attr in ("_cleanup_task", "_republish_task", "_reconnector_task"):
        task = getattr(app.state, attr, None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    await mq.shutdown_amqp(app.state)
    logger.info(f"[{Config.MODULE_NAME}] Shutdown complete")


# =============================================================================
# App
# =============================================================================

app = FastAPI(title=Config.MODULE_NAME, version="2.0.0", debug=True, lifespan=lifespan)

# Initial state
app.state.amqp_enabled = False
app.state.amqp_conn = None
app.state.amqp_ch = None

# Serve ephemeral artifacts
app.mount("/artifacts", StaticFiles(directory=str(Config.ARTIFACTS_ROOT)), name="artifacts")


# =============================================================================
# Artifact cleanup loop (lives here — not AMQP related)
# =============================================================================

async def _cleanup_loop():
    """Periodically clean up old artifacts. Never raises."""
    while True:
        try:
            stats = cleanup_artifacts_once(
                Config.ARTIFACTS_ROOT, Config.ARTIFACTS_RETENTION_HOURS, logger
            )
            logger.debug("Artifacts cleanup stats: %s", stats)
        except Exception as e:
            logger.warning("Artifacts cleanup loop error: %r", e)
        await asyncio.sleep(Config.ARTIFACTS_CLEAN_INTERVAL_SEC)


# =============================================================================
# HTTP endpoints
# =============================================================================

@app.get("/health")
def health():
    artifacts = summarize_artifacts(Config.ARTIFACTS_ROOT)
    return {
        "status": True,
        "module": Config.MODULE_NAME,
        "amqp_enabled": app.state.amqp_enabled,
        "artifacts": artifacts,
    }


@app.post("/run")
async def run(
    request: Request,
    xhtml: UploadFile = File(..., description="XHTML fra forrige steg i pipelinen"),
    mathematics: bool = Form(False),
    science: bool = Form(False),
    grade: Optional[int] = Form(None),
    link_footnotes: bool = Form(False),
    verbose: bool = Form(False),
    toc_levels: Optional[int] = Form(None),
    p_length: Optional[int] = Form(None),
    relocate: bool = Form(True),
    llm: bool = Form(False),
):
    """
    Manual test endpoint — not used by RabbitMQ flow.
    Accepts an XHTML file and returns a zip of artifacts.
    """
    t0 = time.time()
    original_name = xhtml.filename or ""
    suffix = Path(original_name).suffix or ".xhtml"
    production_number = Path(original_name).stem

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", production_number)
    tmp_path = Path(tempfile.gettempdir()) / f"{safe_name}{suffix}"
    with open(tmp_path, "wb") as f:
        f.write(await xhtml.read())

    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S%f")
    job_id = f"{production_number}-{timestamp}"
    job_dir = Config.ARTIFACTS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)  # must exist before convert() saves into it

    args = SimpleNamespace(
        input=tmp_path,
        output=None,
        log_level="INFO",
        folders={},
        production_number=production_number,
        data={},
        mathematics=bool(mathematics),
        science=bool(science),
        grade=grade if grade is not None else None,
        reference_docx=None,
        pandoc_args=[],
        stdout=False,
        no_excel=False,
        job_id=job_id,
        job_dir=job_dir,
        llm=bool(llm),
        toc_levels=toc_levels,
        aggressive=False,
        relocate=bool(relocate),
        logger=logger,
    )

    try:
        status = convert(args)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    logger.info("Conversion completed, preparing artifacts...")

    if not job_dir.is_dir():
        raise HTTPException(500, f"Could not find artifact folder: {job_dir}")

    zip_base = os.path.join(tempfile.gettempdir(), job_id)
    zip_path = shutil.make_archive(zip_base, "zip", job_dir)

    headers = {
        "X-Validation-Status": status.get("status") if isinstance(status, dict) else ("success" if status == 0 else "fail"),
        "X-Processing-Time-ms": str(int((time.time() - t0) * 1000)),
    }
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"{production_number}-artifacts.zip",
        headers=headers,
    )


@app.get("/download/{token}")
async def download(token: str):
    data = DOWNLOADS.pop(token, None)
    if data is None:
        return JSONResponse(status_code=404, content={"error": "File not found"})
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="result.zip"'},
    )


@app.post("/admin/cleanup-artifacts")
async def admin_cleanup_artifacts():
    stats = cleanup_artifacts_once(
        Config.ARTIFACTS_ROOT, Config.ARTIFACTS_RETENTION_HOURS, logger
    )
    return {"ok": True, "retention_hours": Config.ARTIFACTS_RETENTION_HOURS, "stats": stats}
