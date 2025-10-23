from __future__ import annotations

import os
import io
import uuid
import asyncio
import logging
import tempfile
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import aio_pika
import httpx
from fastapi import FastAPI, UploadFile, File, Form, Body, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, PlainTextResponse

# =============================================================================
# Import converter (prefer bok_to_docx; fallback to bok2docx)
# =============================================================================
try:
    import bok_to_docx as converter
except Exception:
    try:
        import bok2docx as converter  # older name
    except Exception as e:
        raise RuntimeError(
            "Finner verken 'bok_to_docx' eller 'bok2docx'. "
            "Sørg for at konverterer-filen ligger i repoet."
        ) from e

# =============================================================================
# Konfigurasjon via miljøvariabler
# =============================================================================
MODULE_NAME = os.getenv("MODULE_NAME", "bok_to_docx")
PORT = int(os.getenv("BOK_TO_DOCX_PORT", "39015"))
BASE_URL = os.getenv("BASE_URL", f"http://localhost:{PORT}")

# AMQP (valgfritt)
AMQP_URL = os.getenv("RABBITMQ_URL", os.getenv("AMQP_URL", ""))
AMQP_QUEUE = os.getenv("BOK_TO_DOCX_QUEUE", "bok_to_docx")
AMQP_PREFETCH = int(os.getenv("AMQP_PREFETCH", "2"))

# Logging
DEFAULT_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger(MODULE_NAME)
logging.getLogger("aio_pika").setLevel(logging.WARNING)
logging.getLogger("aiormq").setLevel(logging.WARNING)

# Paths
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

# =============================================================================
# FastAPI app
# =============================================================================
app = FastAPI(title=MODULE_NAME, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ALLOW_ORIGINS", "*")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Hjelpere
# =============================================================================
def _bool_env(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on"}

def _pandoc_available() -> bool:
    pandoc_bin = os.getenv("PANDOC_BIN", "pandoc")
    from shutil import which
    return which(pandoc_bin) is not None

def _safe_filename(name: str, fallback: str = "output.docx") -> str:
    name = name.strip().replace("/", "_").replace("\\", "_")
    return name or fallback

def _guess_reference_docx(req_ref: Optional[str]) -> Optional[Path]:
    if req_ref:
        p = Path(req_ref)
        if p.exists():
            return p
    candidate = STATIC_DIR / "referenceDoc.docx"
    if candidate.exists():
        return candidate
    return None

async def _convert_bytes(
    xhtml_bytes: bytes,
    *,
    output_filename: str = "output.docx",
    reference_docx: Optional[str | Path] = None,
    pandoc_args: Optional[List[str]] = None,
    grade: Optional[int] = None,
    mathematics: bool = False,
    science: bool = False,
    toc_levels: Optional[int] = None,
    no_excel: bool = False,
) -> bytes:
    ref = None
    if reference_docx:
        ref = Path(reference_docx)
    elif (STATIC_DIR / "referenceDoc.docx").exists():
        ref = STATIC_DIR / "referenceDoc.docx"

    return converter.xhtml_to_docx(
        xhtml_bytes,
        output_filename=_safe_filename(output_filename, "output.docx"),
        reference_docx=ref,
        pandoc_args=pandoc_args or (),
        grade=grade,
        mathematics=mathematics,
        science=science,
        toc_levels=toc_levels,
        no_excel=no_excel,
    )

# =============================================================================
# API Endepunkter
# =============================================================================
@app.get("/", response_class=JSONResponse)
async def root():
    return {
        "module": MODULE_NAME,
        "status": "ok",
        "time": datetime.utcnow().isoformat() + "Z",
        "base_url": BASE_URL,
        "pandoc_available": _pandoc_available(),
        "version": app.version,
        "static_referenceDoc": str(STATIC_DIR / "referenceDoc.docx")
            if (STATIC_DIR / "referenceDoc.docx").exists() else None,
        "amqp_enabled": bool(AMQP_URL),
        "queue": AMQP_QUEUE if AMQP_URL else None,
    }

@app.get("/health", response_class=JSONResponse)
async def health():
    return {
        "status": "ok",
        "pandoc": _pandoc_available(),
        "time": datetime.utcnow().isoformat() + "Z",
    }

@app.get("/version", response_class=PlainTextResponse)
async def version():
    return app.version

# --- POST /convert -----------------------------------------------------------
@app.post("/convert")
async def convert_endpoint(
    # JSON-variant
    xhtml: Optional[str] = Body(default=None),
    reference_docx: Optional[str] = Body(default=None),
    pandoc_args: Optional[List[str]] = Body(default=None),
    grade: Optional[int] = Body(default=None),
    mathematics: bool = Body(default=False),
    science: bool = Body(default=False),
    toc_levels: Optional[int] = Body(default=None),
    no_excel: bool = Body(default=False),
    output_filename: Optional[str] = Body(default=None),

    # Alternativ: multipart opplasting
    file: Optional[UploadFile] = File(default=None),

    # Query-valg
    download: bool = Query(default=True, description="Sett Content-Disposition for nedlasting"),
):
    """
    Konverterer XHTML → DOCX.
    Støtter både JSON (feltet 'xhtml') og multipart (feltet 'file').
    """
    if not _pandoc_available():
        raise HTTPException(status_code=500, detail="Pandoc ikke tilgjengelig (sett PANDOC_BIN eller legg pandoc i PATH).")

    # Innhent bytes
    if xhtml is not None:
        data = xhtml.encode("utf-8")
        inferred_name = output_filename or "output.docx"
    elif file is not None:
        data = await file.read()
        inferred_name = output_filename or (Path(file.filename or "output").with_suffix(".docx").name)
    else:
        raise HTTPException(status_code=400, detail="Mangler input: send 'xhtml' i JSON eller 'file' i multipart.")

    ref = _guess_reference_docx(reference_docx)
    try:
        result = await _convert_bytes(
            data,
            output_filename=inferred_name,
            reference_docx=str(ref) if ref else None,
            pandoc_args=pandoc_args,
            grade=grade,
            mathematics=mathematics,
            science=science,
            toc_levels=toc_levels,
            no_excel=no_excel,
        )
    except Exception as e:
        logger.exception("Konvertering feilet")
        raise HTTPException(status_code=500, detail=f"Konvertering feilet: {e}")

    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{_safe_filename(inferred_name)}"'

    return StreamingResponse(
        io.BytesIO(result),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )

# --- Enkelt GET for å teste at appen svarer, og for å se porten -------------
@app.get("/info", response_class=JSONResponse)
async def info():
    return {
        "module": MODULE_NAME,
        "port": PORT,
        "base_url": BASE_URL,
        "time": datetime.utcnow().isoformat() + "Z",
    }

# =============================================================================
# AMQP (valgfritt): Konsument av jobber fra kø
# =============================================================================
async def _amqp_consumer_loop(conn: aio_pika.RobustConnection):
    ch: aio_pika.RobustChannel = await conn.channel()
    await ch.set_qos(prefetch_count=AMQP_PREFETCH)
    q = await ch.declare_queue(AMQP_QUEUE, durable=True)

    logger.info("AMQP: Lytter på kø: %s", AMQP_QUEUE)

    async with q.iterator() as queue_iter:
        async for msg in queue_iter:
            async with msg.process():
                try:
                    job_id = msg.message_id or str(uuid.uuid4())
                    logger.info("AMQP: mottok job %s", job_id)
                    payload = msg.body.decode("utf-8", errors="replace")

                    # Forventer rå XHTML i body. Alternativt kunne vi støttet JSON.
                    result = await _convert_bytes(
                        payload.encode("utf-8"),
                        output_filename=f"{job_id}.docx",
                        reference_docx=str(_guess_reference_docx(None) or ""),
                        pandoc_args=None,
                    )

                    # Publiser svar på reply_to hvis satt, ellers dropp (fire-and-forget)
                    if msg.reply_to:
                        await ch.default_exchange.publish(
                            aio_pika.Message(
                                body=result,
                                correlation_id=msg.correlation_id,
                                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            ),
                            routing_key=msg.reply_to,
                        )
                        logger.info("AMQP: publiserte svar for job %s", job_id)
                except Exception:
                    logger.exception("AMQP: feil ved behandling av melding")

@app.on_event("startup")
async def on_startup():
    app.state.tasks: list[asyncio.Task] = []

    if AMQP_URL:
        try:
            conn = await aio_pika.connect_robust(AMQP_URL)
            app.state.amqp_conn = conn
            task = asyncio.create_task(_amqp_consumer_loop(conn))
            app.state.tasks.append(task)
            logger.info("AMQP: tilkoblet %s, kø=%s", AMQP_URL, AMQP_QUEUE)
        except Exception:
            logger.exception("AMQP: klarte ikke koble til")

@app.on_event("shutdown")
async def on_shutdown():
    # stop tasks
    for t in getattr(app.state, "tasks", []):
        t.cancel()
        with suppress(asyncio.CancelledError):
            await t

    # close AMQP
    ch = getattr(app.state, "amqp_ch", None)
    if ch:
        with suppress(Exception):
            await ch.close()
    conn = getattr(app.state, "amqp_conn", None)
    if conn:
        with suppress(Exception):
            await conn.close()

# =============================================================================
# Lokal kjøring (uvicorn)
# =============================================================================
if __name__ == "__main__":
    import uvicorn
    logger.info("Starter %s på port %s ...", MODULE_NAME, PORT)
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, log_level=DEFAULT_LOG_LEVEL.lower())
