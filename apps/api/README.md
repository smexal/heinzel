# Heinzel API

FastAPI core: tenants, identity, permissions, audit, module host, MCP gateway (later).

```bash
uv sync
uv run heinzel migrate                 # schema core, role heinzel_app, RLS policies
uv run heinzel seed-tenants            # register tenants/<slug> and their system roles
uv run heinzel create-admin --tenant schmelzi --email you@example.org --name "Vorname Name"
uv run uvicorn heinzel_api.main:app --reload --port 8000
uv run pytest                          # needs Postgres (docker compose); creates heinzel_test
uv run ruff check . && uv run ruff format --check .
```

OpenAPI UI: http://localhost:8000/docs

## Database roles

| Role | Used by | Rights |
| --- | --- | --- |
| `heinzel` (owner) | migrations, CLI | owns schema `core`; RLS is forced, so it also has to bind a tenant |
| `heinzel_app` | the running API | read/write tenant tables through RLS, read-only tenant registry, insert-only audit log |

Every request binds its transaction to one tenant (`set_config('app.tenant_id', …, true)`); the
policies show and accept only that tenant's rows. Migrations of new tenant tables call
`heinzel_api.migration_helpers.tenant_table_security()`.

## Endpoints so far

| Endpoint | |
| --- | --- |
| `GET /api/v1/shell` | branding (public); navigation and quick actions filtered by permission |
| `POST /api/v1/auth/login` | e-mail + password; answers `next`: `done`, `totp` or `mfa_setup` |
| `POST /api/v1/auth/totp` | second factor |
| `POST /api/v1/auth/mfa/setup`, `/mfa/confirm` | TOTP enrolment (QR as SVG data URI) |
| `POST /api/v1/auth/logout` | |
| `GET /api/v1/me` | user, roles, permissions, effective localisation |
