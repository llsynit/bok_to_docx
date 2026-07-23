FROM python:3.12-alpine3.24

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODULE_NAME=bok2docx \
    PORT=34504 \
    APP_HOME=/app \
    LOG_LEVEL=INFO

WORKDIR ${APP_HOME}

RUN apk upgrade --no-cache \
    && apk add --no-cache pandoc-cli

# Pandoc required for conversion
RUN apk add --no-cache \
        pandoc-cli

COPY requirements.txt ./requirements.txt

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Opprett gruppe og ikke-root-bruker med UID/GID 1000
RUN addgroup -g 1000 -S appuser \
    && adduser -u 1000 -S -D -H -G appuser appuser \
    && chown -R appuser:appuser ${APP_HOME}

COPY --chown=appuser:appuser . ${APP_HOME}

RUN mkdir -p ${APP_HOME}/static \
    && chown -R appuser:appuser ${APP_HOME}/static

USER appuser

EXPOSE 34504

HEALTHCHECK --interval=20s --timeout=3s --retries=5 \
    CMD python -c "import socket; s=socket.create_connection(('127.0.0.1', 34504), 2); s.close()"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "34504"]
