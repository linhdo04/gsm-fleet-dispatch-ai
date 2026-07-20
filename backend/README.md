# Fleet Dispatch Backend

Production-oriented FastAPI foundation managed with `uv`.

## Local development

```bash
cp .env.example .env
uv sync --frozen
uv run uvicorn fleet_dispatch.main:app --reload
```

API documentation is available at <http://localhost:8000/docs>.

## Quality checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## Endpoints

- `GET /api/v1/health/live`: process liveness.
- `GET /api/v1/health/ready`: dependency readiness; extend when adding the database/cache.
- `GET /metrics`: Prometheus metrics.
- `GET /docs`: OpenAPI UI in environments where docs are enabled.

All application variables use the `APP_` prefix. Lists such as `APP_CORS_ORIGINS`
and `APP_TRUSTED_HOSTS` use JSON syntax; see `.env.example`.

Set `APP_OTEL_ENABLED=true` to export traces using OTLP/gRPC. Logs are JSON by default in
the container and contain a propagated `request_id`. Send `X-Request-ID` to preserve a caller's
correlation ID; otherwise the API creates one and returns it in the response.
