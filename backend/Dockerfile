FROM dhi.io/uv:0 AS uv

FROM dhi.io/python:3.13-dev AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY --from=uv /usr/local/bin/uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --output-file requirements.txt
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
COPY --from=builder /app/site-packages /app/site-packages

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "fleet_dispatch.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers"]
