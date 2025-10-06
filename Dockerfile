FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODULE_NAME=bok_to_docx \
    PORT=9004 \
    APP_HOME=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_PREFER_BINARY=1

WORKDIR ${APP_HOME}

# Systemavhengigheter: pandoc for konvertering
RUN apt-get update \
 && apt-get install -y --no-install-recommends pandoc \
 && rm -rf /var/lib/apt/lists/*

# Python-avhengigheter
COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip setuptools wheel \
 && pip install -r requirements.txt

# Kildekode
COPY app.py ./app.py
COPY bok2docx.py ./bok2docx.py
# Hjelpemoduler fra repoet ditt:
COPY clean.py ./clean.py
COPY pandoc_wrapper.py ./pandoc_wrapper.py
COPY prepareXdocx.py ./prepareXdocx.py

# Ikke-root
RUN useradd -ms /bin/bash appuser
USER appuser

EXPOSE 9004
HEALTHCHECK --interval=20s --timeout=3s --retries=5 \
  CMD python -c "import socket; s=socket.create_connection(('127.0.0.1', 9004), 2); s.close()"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9004"]
