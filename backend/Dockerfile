FROM dhi.io/uv:0 AS uv

FROM dhi.io/python:3.13-dev AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY --from=uv /usr/local/bin/uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./

RUN uv export \
    --frozen \
    --no-dev \
    --no-emit-project \
    --output-file requirements.txt

RUN uv pip install \
    --python python \
    --target /app/site-packages \
    --requirements requirements.txt

COPY README.md ./
COPY src ./src

RUN uv pip install \
    --python python \
    --target /app/site-packages \
    --no-deps \
    .


FROM dhi.io/python:3.13 AS runtime

ENV PYTHONPATH="/app/site-packages" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENVIRONMENT=production \
    APP_LOG_FORMAT=json

WORKDIR /app

COPY --from=builder \
    --chown=65532:65532 \
    /app/site-packages \
    /app/site-packages

USER 65532:65532

EXPOSE 8000

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=10s \
    --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"]


CMD ["python", "-m", "uvicorn", "fleet_dispatch.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers"]
