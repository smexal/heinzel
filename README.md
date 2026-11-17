# Heinzel

Modular, multi-tenant company portal. One place where staff find their tools, handle their tasks
and get administrative work done. First tenant: Stiftung Schmelzi.

- Concept: [`docs/`](docs/README.md)
- Guidance for Claude Code: [`CLAUDE.md`](CLAUDE.md)

## Prerequisites

- Docker Desktop (for Postgres, Valkey, Mailpit)
- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Node.js 22.17+ and pnpm 10+ (`corepack enable` or `npm i -g pnpm`)

## Run locally

```bash
cp .env.example .env
docker compose up -d

# API on http://localhost:8000 (OpenAPI UI at /docs)
cd apps/api
uv sync
uv run uvicorn heinzel_api.main:app --reload --port 8000

# Web on http://localhost:5173 (second terminal, repo root)
pnpm install
pnpm dev:web
```

Mail sent in dev is caught by Mailpit: http://localhost:8025

## Checks

```bash
cd apps/api && uv run pytest -q && uv run ruff check .
pnpm check:web && pnpm build:web
```

## Layout

| Path | Content |
| --- | --- |
| `apps/api` | FastAPI core: tenants, identity, permissions, module host |
| `apps/web` | SvelteKit web app: shell, core screens, module screens |
| `modules/` | One folder per module: manifest, settings schema, later code |
| `tenants/` | Tenant configuration and assets (dev seed) |
| `docs/` | Concept snapshots |
