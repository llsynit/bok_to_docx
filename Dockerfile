# Slank Python-base
FROM python:3.12-slim

# --- Miljø ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODULE_NAME=bok_to_docx \
    APP_HOME=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_PREFER_BINARY=1 \
    BOK_TO_DOCX_PORT=39015 \
    LOG_LEVEL=INFO

WORKDIR ${APP_HOME}

# --- Systemavhengigheter ---
# Pandoc trengs for konverteringen (bok_to_docx → DOCX)
RUN apt-get update \
 && apt-get install -y --no-install-recommends pandoc \
 && rm -rf /var/lib/apt/lists/*

# --- Python-avhengigheter ---
# Bruk lag-cache: kopier kun requirements først
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r /tmp/requirements.txt \
 && rm -f /tmp/requirements.txt

# --- App-kode ---
# Kopierer hele repoet (app.py, bok_to_docx.py, statiske filer, osv.)
COPY . .

# Sikre at kataloger finnes (brukes av app/konverterer)
RUN mkdir -p ${APP_HOME}/static ${APP_HOME}/output

# --- Non-root ---
# UID 10001 som i andre moduler; gi skrivetilgang til appen
RUN useradd -m -u 10001 appuser \
 && chown -R appuser:appuser ${APP_HOME}
USER appuser

# --- Nett/Health ---
EXPOSE 39015
HEALTHCHECK --interval=20s --timeout=3s --retries=5 \
  CMD python -c "import socket; s=socket.create_connection(('127.0.0.1', 39015), 3); s.close()"

# --- Start ---
# Holder samme stil som referansemodulene (fast port i CMD).
# (Du kan fortsatt mappe valgfri port i docker compose.)
# CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "39015"]
CMD ["/bin/sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${BOK_TO_DOCX_PORT:-39015}"]
