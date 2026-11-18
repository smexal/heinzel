# Heinzel API

FastAPI core: tenants, identity, permissions, audit, module host, MCP gateway (later).

```bash
uv sync
uv run heinzel migrate                 # schema core, role heinzel_app, RLS policies
uv run heinzel seed-tenants            # register tenants/<slug> (settings only for new tenants)
uv run heinzel seed-tenants --reset-config   # overwrite settings and logos from tenants/<slug>
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
| `POST /api/v1/me/password` | change own password (other sessions end) |
| `POST /api/v1/auth/password/forgot` | always 202; mails a reset link to active users |
| `GET /api/v1/auth/token/{token}` | what an invitation or reset link is for |
| `POST /api/v1/auth/password/set` | redeem the link: set password, activate invited users |
| `GET /api/v1/admin/users` | users with roles, MFA state, last login (`core.users.manage`) |
| `POST /api/v1/admin/users` | invite (mail with a 7-day link) |
| `POST /api/v1/admin/users/{id}/invite \| deactivate \| activate \| mfa-reset` | |
| `PUT /api/v1/admin/users/{id}/roles` | replace role assignments (step-up) |
| `GET /api/v1/me/preferences`, `PUT …` | language and regional settings: own values, tenant defaults, locks, options |
| `GET /api/v1/admin/audit` | events, newest first; filters `q, actor, channel, area, since`; paging `before_id`; chain status (`core.audit.read`) |
| `GET /api/v1/admin/audit/export.csv` | same filters as CSV (`;`, UTF-8 with BOM); the export is audited |
| `POST /api/v1/auth/step-up` | re-confirm with TOTP (or password without 2FA) for 10 minutes |
| `POST /api/v1/admin/roles`, `PUT/DELETE …/{key}` | custom roles (`core.roles.manage`, step-up) |
| `GET /api/v1/admin/settings` | all sections, version, options (`core.settings.manage`) |
| `PUT /api/v1/admin/settings/{general\|branding\|localization}` | save a section `{version, values}`; 409 on a stale version |
| `PUT /api/v1/admin/settings/secure/{identity\|email}` | same, with step-up |
| `PUT/DELETE /api/v1/admin/settings/branding/logos/{light\|dark\|mark}` | logo upload (raw body: SVG, PNG, WebP, ≤ 512 KB) |
| `POST /api/v1/admin/settings/email/test` | test mail to the signed-in admin |
| `GET /api/v1/admin/modules` | modules with status, area, children, permissions + roles, settings schema/values, MCP items |
| `PUT /api/v1/admin/modules/{key}` | activate/deactivate, area, hidden children, settings (JSON Schema), `mcp_disabled` |
| `PUT /api/v1/admin/settings/navigation` | areas in order (`key` null = new), `hide_empty_areas` |
| `GET /api/v1/admin/roles` | roles with expanded permissions and the permission catalogue |
