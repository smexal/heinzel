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

Two ways, both from the repository root:

| | Command | Open | When |
| --- | --- | --- | --- |
| Development | `pnpm dev` | http://localhost:5173 | Coding: API and web on your machine with hot reload, Postgres/Valkey/Mailpit in Docker |
| Full stack | `pnpm stack` (`docker compose up -d --build`) | http://localhost:8080 | Trying it out or demoing: everything in containers behind a Caddy proxy, like production |

`pnpm dev` creates `.env` from `.env.example` if missing, starts the containers, runs
`uv sync`, the migrations and `seed-tenants`, then starts API and web with prefixed output.
Ctrl+C stops API and web; the containers keep running (`docker compose stop` ends them).
Use `pnpm dev --no-docker` if Postgres, Valkey and Mailpit run elsewhere.

The full stack runs migrations and `seed-tenants` in a one-off `migrate` container before the API
starts. `pnpm stack:down` stops it; add `-v` to `docker compose down` to drop the database.

**First administrator** (once per database), then sign in and set up two-factor:

```bash
# pnpm dev
cd apps/api && uv run heinzel create-admin --tenant schmelzi --email you@schmelzi.ch --name "Vorname Name"
# pnpm stack
docker compose exec api heinzel create-admin --tenant schmelzi --email you@schmelzi.ch --name "Vorname Name"
```

Mail sent in dev (invitations, password reset) is caught by Mailpit: http://localhost:8025

## Production and moving data

`compose.prod.yml` runs everything on one server behind Caddy with HTTPS, ClamAV and a daily
backup; `deploy/heinzel.sh` operates it. Step by step: [deploy/README.md](deploy/README.md).

Data moves between installations as one file: `pnpm heinzel export` (all tenants' database rows
and stored files into `var/exports/`), `heinzel import FILE` on the other side. Both must run the
same version; secrets are re-encrypted for the target's `HEINZEL_SECRET_KEY`.

**Tenant settings** live in the database. `tenants/<slug>/tenant.json` and its `assets/` only seed a
new tenant; afterwards admins change them under Administration › Einstellungen. To start over from
the files: `cd apps/api && uv run heinzel seed-tenants --reset-config`.

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
