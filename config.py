# config.py
import os
import socket
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
# loads .env if present; safe in Docker too
load_dotenv(find_dotenv(), override=False)

# =============================================================================
# Config (env) — no Redis anywhere, pure RabbitMQ
# =============================================================================

MODULE_NAME_BOK_TO_DOCX = os.getenv("MODULE_NAME_BOK_TO_DOCX", "bok_to_docx")
PORT_BOK_TO_DOCX = int(os.getenv("PORT_BOK_TO_DOCX", "39015"))

print(f"Starting {MODULE_NAME_BOK_TO_DOCX} on port {PORT_BOK_TO_DOCX}.....")

# RabbitMQ
RABBITMQ_URL = None
RABBITMQ_URL_DOCKER = os.getenv("RABBITMQ_URL_DOCKER")
RABBITMQ_URL_LOCAL = os.getenv("RABBITMQ_URL_LOCAL")

if RABBITMQ_URL_DOCKER:
    try:
        # check if Docker hostname is resolvable
        socket.gethostbyname("rabbitmq")
        RABBITMQ_URL = RABBITMQ_URL_DOCKER
        print("Using RABBITMQ_URL_DOCKER")
    except socket.gaierror:
        if RABBITMQ_URL_LOCAL:
            RABBITMQ_URL = RABBITMQ_URL_LOCAL
            print("Docker hostname not found, falling back to RABBITMQ_URL_LOCAL")
        else:
            raise RuntimeError(
                "RabbitMQ hostname not resolvable and no local URL set")
elif RABBITMQ_URL_LOCAL:
    RABBITMQ_URL = RABBITMQ_URL_LOCAL
    print("Using RABBITMQ_URL_LOCAL")
else:
    raise RuntimeError(
        "Either RABBITMQ_URL_DOCKER or RABBITMQ_URL_LOCAL must be set")

print(f"Connecting to RabbitMQ: {RABBITMQ_URL}")

WORK_EXCHANGE = os.getenv("WORK_EXCHANGE", "work.ex")            # direct
RESULTS_EXCHANGE = os.getenv("RESULTS_EXCHANGE", "results.ex")   # topic
WORK_ROUTING_KEY = os.getenv(
    "WORK_ROUTING_KEY_BOK_TO_DOCX", "bok_to_docx")     # stage name
WORK_QUEUE_NAME = os.getenv(
    "WORK_QUEUE_NAME_BOK_TO_DOCX", "bok_to_docx.q")     # durable queue

# Artifacts are EPHEMERAL here — the controller should fetch and persist them.
WORKER_BASE_URL = os.getenv(
    "WORKER_BASE_URL_BOK_TO_DOCX", f"http://{MODULE_NAME_BOK_TO_DOCX}:{PORT_BOK_TO_DOCX}")


BASE_DIR = Path(__file__).parent
ARTIFACTS_ROOT = (BASE_DIR / "artifacts").resolve()
ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)

ARTIFACTS_RETENTION_HOURS = int(
    os.getenv("ARTIFACTS_RETENTION_HOURS", "24"))  # default 24h
ARTIFACTS_CLEAN_INTERVAL_SEC = int(
    os.getenv("ARTIFACTS_CLEAN_INTERVAL_SEC", "900"))  # default 15 min
