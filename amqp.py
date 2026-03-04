# amqp.py — all RabbitMQ logic for bok_to_docx
import asyncio
import json
import time
import uuid
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional
from urllib.parse import urlparse

import aio_pika
import httpx
from aiormq.exceptions import AMQPConnectionError, ChannelInvalidStateError
from fastapi import HTTPException

from bok2docx import convert
from config import Config, logger


# =============================================================================
# Helpers
# =============================================================================

def _art_uri(job_id: str, name: str) -> str:
    return f"{Config.WORKER_BASE_URL}/artifacts/{job_id}/{name}"


async def _http_download_to(dst: Path, url: str):
    """Download http(s) or copy file:// to dst."""
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


# =============================================================================
# Result publishing
# =============================================================================

async def _publish_result(
    app_state,
    stage: str,
    job_id: str,
    status: str,
    artifacts: Dict,
    correlation_id: Optional[str],
):
    rk = f"job.{job_id}.stage.{stage}.status.{status}"
    payload = {
        "job_id": job_id,
        "stage": stage,
        "status": status,
        "artifacts": artifacts,
        "finished_at": time.time(),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    msg = aio_pika.Message(
        body=body,
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        correlation_id=correlation_id,
        message_id=str(uuid.uuid4()),
    )
    if not getattr(app_state, "results_ex", None):
        raise RuntimeError("results_ex not set on app_state — AMQP not fully connected")
    logger.info(f"[{job_id}] Publishing to results exchange, routing_key='{rk}'")
    await app_state.results_ex.publish(msg, routing_key=rk)
    logger.info(f"[{job_id}] Published OK")


async def _save_and_publish_result(
    app_state,
    stage: str,
    job_id: str,
    status: str,
    artifacts: Dict,
    correlation_id: Optional[str],
):
    """Save result to disk first, then try to publish to RabbitMQ."""
    result_data = {
        "job_id": job_id,
        "stage": stage,
        "status": status,
        "artifacts": artifacts,
        "correlation_id": correlation_id,
        "finished_at": time.time(),
        "published": False,
    }

    result_file = Config.ARTIFACTS_ROOT / job_id / "result.json"
    try:
        result_file.write_text(json.dumps(result_data, indent=2, ensure_ascii=False))
        logger.info(f"[{job_id}] Result saved to disk")
    except Exception as e:
        logger.error(f"[{job_id}] CRITICAL: Failed to save result: {e}")

    try:
        if not app_state.amqp_enabled:
            logger.warning(f"[{job_id}] AMQP not connected, result saved locally only")
            return

        await _publish_result(app_state, stage, job_id, status, artifacts, correlation_id)

        result_data["published"] = True
        result_file.write_text(json.dumps(result_data, indent=2, ensure_ascii=False))
        logger.info(f"[{job_id}] Result published to RabbitMQ")

    except (ChannelInvalidStateError, AMQPConnectionError) as e:
        logger.warning(
            f"[{job_id}] Failed to publish result: {e}. "
            "Saved locally — will republish on reconnect."
        )
    except Exception as e:
        logger.error(f"[{job_id}] Unexpected error publishing: {e}")


# =============================================================================
# Work message handler (consumer callback)
# =============================================================================

def _make_message_handler(app_state):
    """Return an async handler bound to app.state."""

    async def _handle_work_message(m: aio_pika.IncomingMessage):
        logger.info(f"[AMQP] Message received — routing_key='{m.routing_key}', delivery_tag={m.delivery_tag}")
        job_id = None
        try:
            async with m.process():
                data = json.loads(m.body.decode("utf-8"))
                job_id = data.get("job_id")
                stage = data.get("stage") or "bok_to_docx"
                inputs = data.get("inputs") or {}
                corr_id = data.get("correlation_id") or m.correlation_id
                production_number = str(data.get("production_number") or "")

                logger.info(f"[{Config.MODULE_NAME}] job {job_id} stage {stage} started...")
                logger.info(f"production_number: {production_number}")

                xhtml_uri = inputs.get("xhtml_uri")

                if not (job_id and xhtml_uri and production_number):
                    logger.error(f"[{job_id or '?'}] Missing required fields")
                    await _publish_result(
                        app_state, stage, job_id or "?", "fail",
                        {"error": "missing job_id/xhtml_uri/production_number"},
                        corr_id,
                    )
                    return

                # Workspace
                job_dir = Config.ARTIFACTS_ROOT / job_id
                job_dir.mkdir(parents=True, exist_ok=True)

                # Idempotency check
                result_file = job_dir / "result.json"
                if result_file.exists():
                    logger.info(f"[{job_id}] Job already processed, republishing result")
                    result_data = json.loads(result_file.read_text())
                    if not result_data.get("published", False):
                        await _publish_result(
                            app_state,
                            result_data["stage"],
                            job_id,
                            result_data["status"],
                            result_data["artifacts"],
                            result_data.get("correlation_id"),
                        )
                        result_data["published"] = True
                        result_file.write_text(json.dumps(result_data, indent=2))
                        logger.info(f"[{job_id}] Result republished successfully")
                    else:
                        logger.info(f"[{job_id}] Result already published, acknowledging message")
                    return

                # Download input
                tmp_xhtml = job_dir / "input.xhtml"
                await _http_download_to(tmp_xhtml, xhtml_uri)

                args = SimpleNamespace(
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
                    logger=logger,
                )

                logger.info(f"[{job_id}] Starting processing")
                try:
                    status = convert(args)
                    logger.info(f"[{job_id}] Processing finished with status {status}")
                except Exception as e:
                    logger.error(f"[{job_id}] Processing failed: {e}", exc_info=True)
                    await _save_and_publish_result(
                        app_state, stage, job_id, "fail",
                        {"error": f"bok_to_docx crashed: {e}"},
                        corr_id,
                    )
                    return

                if not job_dir.exists():
                    logger.error(f"[{job_id}] Output directory missing")
                    await _save_and_publish_result(
                        app_state, stage, job_id, "fail",
                        {"error": f"Could not find artifact folder: {job_dir}"},
                        corr_id,
                    )
                    return

                # Collect artifacts
                artifacts = {}
                excluded_files = {
                    "result.json", "input.xhtml", "input.html",
                    f"{production_number}_prepared.html",
                }
                for path in job_dir.rglob("*"):
                    if not path.is_file():
                        continue
                    if "images" in path.parts:
                        continue
                    if path.name in excluded_files:
                        logger.debug(f"[{job_id}] Excluding: {path.name}")
                        continue
                    artifact_name = str(path.relative_to(job_dir))
                    artifact_url = _art_uri(job_id, artifact_name)
                    logger.info(f"[{job_id}] Adding artifact: {artifact_name} -> {artifact_url}")
                    artifacts[artifact_name] = artifact_url

                status_value = (
                    status.get("status", "ok") if isinstance(status, dict)
                    else ("success" if status == 0 else "fail")  # 0 = success, 1/2 = fail
                )

                logger.info(f"[{job_id}] Processing completed with status: {status_value}")
                await _save_and_publish_result(
                    app_state, stage, job_id, status_value, artifacts, corr_id
                )

        except ChannelInvalidStateError:
            logger.warning(
                f"[{job_id or '?'}] Channel closed during processing. "
                "Message will be redelivered automatically."
            )
        except Exception as e:
            logger.error(f"[{job_id or '?'}] Unexpected error: {e}", exc_info=True)

    return _handle_work_message


# =============================================================================
# Connection setup
# =============================================================================

def _on_reconnect(connection, app_state):
    logger.info(f"[{Config.MODULE_NAME}] AMQP connection restored!")
    app_state.amqp_enabled = True


def _on_connection_lost(connection, exc, app_state):
    logger.warning(f"[{Config.MODULE_NAME}] AMQP connection lost: {exc}")
    app_state.amqp_enabled = False


async def setup_amqp(app_state) -> bool:
    """
    Connect to RabbitMQ, declare exchanges/queue, and start consuming.
    Returns True on success, False on failure. Never raises.
    """
    if not Config.RABBITMQ_URL:
        logger.warning(
            f"[{Config.MODULE_NAME}] No RABBITMQ_URL configured. "
            "Running without RabbitMQ — HTTP endpoints remain available."
        )
        app_state.amqp_enabled = False
        return False

    try:
        conn = await aio_pika.connect_robust(
            Config.RABBITMQ_URL,
            reconnect_interval=10,
            fail_fast=True,   # Raise immediately if unavailable; reconnector loop handles retries
        )
        conn.reconnect_callbacks.add(lambda c: _on_reconnect(c, app_state))
        conn.close_callbacks.add(lambda c, exc: _on_connection_lost(c, exc, app_state))

        ch = await conn.channel()
        await ch.set_qos(prefetch_count=1)

        work_ex = await ch.declare_exchange(
            Config.WORK_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
        )
        results_ex = await ch.declare_exchange(
            Config.RESULTS_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
        )

        q = await ch.declare_queue(Config.WORK_QUEUE_NAME, durable=True)
        await q.bind(work_ex, routing_key=Config.WORK_ROUTING_KEY)
        await q.consume(_make_message_handler(app_state))

        app_state.amqp_conn = conn
        app_state.amqp_ch = ch
        app_state.work_ex = work_ex
        app_state.results_ex = results_ex
        app_state.amqp_enabled = True

        logger.info(
            f"[{Config.MODULE_NAME}] AMQP connected and consuming from '{Config.WORK_QUEUE_NAME}'"
        )
        return True

    except (AMQPConnectionError, OSError, ConnectionRefusedError) as e:
        logger.warning(
            f"[{Config.MODULE_NAME}] AMQP connection failed: {e}. "
            "Will retry in background every 10 s. HTTP endpoints remain available."
        )
        app_state.amqp_enabled = False
        return False


async def shutdown_amqp(app_state):
    """Close AMQP channel and connection cleanly."""
    ch = getattr(app_state, "amqp_ch", None)
    if ch:
        with suppress(Exception):
            await ch.close()
    conn = getattr(app_state, "amqp_conn", None)
    if conn:
        with suppress(Exception):
            await conn.close()
    app_state.amqp_enabled = False
    logger.info(f"[{Config.MODULE_NAME}] AMQP connection closed")


# =============================================================================
# Background tasks
# =============================================================================

async def amqp_reconnector_loop(app_state):
    """
    Retries RabbitMQ connection every 10 seconds when disconnected. Never raises.
    """
    while True:
        await asyncio.sleep(10)
        if app_state.amqp_enabled:
            continue
        if not Config.RABBITMQ_URL:
            continue
        logger.info(f"[{Config.MODULE_NAME}] Retrying RabbitMQ connection...")
        try:
            ok = await setup_amqp(app_state)
            if ok:
                logger.info(f"[{Config.MODULE_NAME}] RabbitMQ reconnected successfully.")
        except Exception as e:
            logger.warning(f"[{Config.MODULE_NAME}] Reconnect attempt failed: {e}")


async def republish_pending_results(app_state):
    """
    Every 60 s, scans artifacts for result.json files not yet published and retries.
    """
    while True:
        try:
            await asyncio.sleep(60)

            if not app_state.amqp_enabled:
                continue

            cutoff_time = time.time() - 5

            for result_file in Config.ARTIFACTS_ROOT.rglob("result.json"):
                try:
                    if result_file.stat().st_mtime > cutoff_time:
                        continue

                    result_data = json.loads(result_file.read_text())
                    if result_data.get("published", False):
                        continue

                    job_id = result_data["job_id"]
                    logger.info(f"[{job_id}] Republishing pending result")

                    await _publish_result(
                        app_state,
                        result_data["stage"],
                        job_id,
                        result_data["status"],
                        result_data["artifacts"],
                        result_data.get("correlation_id"),
                    )

                    result_data["published"] = True
                    result_file.write_text(json.dumps(result_data, indent=2))
                    logger.info(f"[{job_id}] Pending result republished")

                except Exception as e:
                    logger.warning(f"Failed to republish result from {result_file}: {e}")

        except Exception as e:
            logger.error(f"Error in republish loop: {e}")
