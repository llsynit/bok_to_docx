# config.py
import os
import socket
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

MODULE_NAME_STATPUB_TO_BOK = os.getenv(
    "MODULE_NAME_BOK_TO_DOCX", "bok_to_docx")
PORT_STATPUB_TO_BOK = int(os.getenv("PORT_BOK_TO_DOCX", "39015"))

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

# RabbitMQ exchanges, queues, routing keys

WORK_EXCHANGE = os.getenv("WORK_EXCHANGE", "work.ex")            # direct
RESULTS_EXCHANGE = os.getenv("RESULTS_EXCHANGE", "results.ex")   # topic
WORK_ROUTING_KEY_STATPUB_TO_BOK = os.getenv(
    "WORK_ROUTING_KEY_BOK_TO_DOCX", "bok_to_docx")     # stage name
WORK_QUEUE_NAME_STATPUB_TO_BOK = os.getenv(
    "WORK_QUEUE_NAME_BOK_TO_DOCX", "bok_to_docx.q")     # durable queue

# Artifacts are EPHEMERAL here — the controller should fetch and persist them.

WORKER_BASE_URL = os.getenv(
    "WORKER_BASE_URL_BOK_TO_DOCX", f"http://{MODULE_NAME_BOK_TO_DOCX}:{PORT_BOK_TO_DOCX}")

print(f"Controller fetchdes artifacts from worker base url: {WORKER_BASE_URL}")
BASE_DIR = Path(__file__).parent
ARTIFACTS_ROOT = (BASE_DIR / "artifacts").resolve()
ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)

ARTIFACTS_RETENTION_HOURS = int(
    os.getenv("ARTIFACTS_RETENTION_HOURS", "24"))  # default 24h
ARTIFACTS_CLEAN_INTERVAL_SEC = int(
    os.getenv("ARTIFACTS_CLEAN_INTERVAL_SEC", "900"))  # default 15 min
