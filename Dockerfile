FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODULE_NAME=bok2docx \
    PORT=34504 \
    APP_HOME=/app \
    LOG_LEVEL=INFO

WORKDIR ${APP_HOME}

# pandoc required for conversion
RUN apt-get update \
    && apt-get install -y --no-install-recommends pandoc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

RUN useradd -u 1000 -ms /bin/bash appuser \
    && chown -R appuser:appuser /app

COPY --chown=appuser:appuser . /app

RUN mkdir -p ${APP_HOME}/static
COPY --chown=appuser:appuser static/ ${APP_HOME}/static/

USER appuser

EXPOSE 34504
HEALTHCHECK --interval=20s --timeout=3s --retries=5 CMD python -c \
    "import socket; s=socket.create_connection(('127.0.0.1', 34504), 2); s.close()"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "34504"]