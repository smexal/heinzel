# Heinzel API

FastAPI core: tenants, identity, permissions, module host, MCP gateway (later).

```bash
uv sync
uv run uvicorn heinzel_api.main:app --reload --port 8000
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Open http://localhost:8000/docs for the OpenAPI UI. `GET /api/v1/shell` returns branding and
navigation for the tenant resolved from the host name (`localhost` maps to Stiftung Schmelzi in dev).
