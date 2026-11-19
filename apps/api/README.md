# Heinzel API

FastAPI core: tenants, identity, permissions, audit, module host, MCP gateway (later).

```bash
uv sync
uv run heinzel migrate                 # core (schema core, role heinzel_app, RLS), then every module
uv run heinzel export [--out DIR|FILE] [--keep N]   # all data and files into one .tar.gz (var/exports/)
uv run heinzel import FILE [--replace] [--source-key KEY]   # replace all data with an export
uv run heinzel run-jobs [aufgaben.reminders]   # module jobs once (the API also runs them itself)
uv run heinzel seed-tenants            # register tenants/<slug> (settings only for new tenants)
uv run heinzel seed-tenants --reset-config   # overwrite settings and logos from tenants/<slug>
uv run heinzel create-admin --tenant schmelzi --email you@example.org --name "Vorname Name"
uv run heinzel demo-inbox --tenant schmelzi --email you@example.org   # sample items in Mein Eingang
uv run heinzel reindex-search          # rebuild the core's search index (seed-tenants does this too)
uv run heinzel files verify            # every stored file present and matching its checksum
uv run heinzel files copy --to D:\heinzel-files   # copy all files elsewhere (moving storage)
uv run uvicorn heinzel_api.main:app --reload --port 8000
uv run pytest                          # needs Postgres (docker compose); creates heinzel_test
uv run ruff check . && uv run ruff format --check .
```

Every command except `migrate` stops with a hint when migrations are pending.

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
| `POST /api/v1/files?module=<id>` | upload (raw body, `X-Filename`); type sniffed (pictures, PDF, docx/xlsx/pptx, odt/ods/odp, TXT/CSV; no macros, archives or programs), size limit, virus scan; staged until linked |
| `GET /api/v1/files/{id}` | download if allowed (uploader, inbox recipient, or the module's access check) |
| `GET /api/v1/inbox?view=open\|notices\|done&source=` | Mein Eingang with counts and sources |
| `POST /api/v1/inbox/{id}/read\|unread\|done\|reopen`, `/read-all` | item state |
| `POST /api/v1/inbox/{id}/actions/{key}` | action button, handled by the source module |
| `GET /api/v1/home` | Übersicht widgets of active modules |
| `/api/v1/<module>/...` | module routes (Aufgaben: see modules/aufgaben/README.md); 404 while the module is off |
| `GET /api/v1/search?q=&group=` | global search: pages, people (user admins), module entities; permission-filtered twice |
| `GET /api/v1/admin/roles` | roles with expanded permissions and the permission catalogue |

## Search

`heinzel_api.search` keeps one index (`core.search_document`, tsvector with unaccent; simple
prefix matching plus German stemming). Modules call `search.index(...)` / `search.remove(...)`
in the same transaction as the change and may register a `can_view` check with
`search.register_provider(module, type, can_view=...)`; label and icon come from the manifest
(`contributes.search_providers: [{type, label, icon}]`). A query only covers active modules
(not switched off with `search_enabled: false`) and documents whose `permission` the user holds,
then runs each provider's `can_view`. People are indexed automatically when a user's name,
e-mail or status changes. Pages (navigation, admin pages, settings and profile tabs) are matched
live. Never index sensitive fields.

## File storage

Files stay on this machine for now: `HEINZEL_STORAGE=local` (the only backend) with
`HEINZEL_FILES_DIR` (dev: `var/files`; Docker stack: the `files` volume, `/data/files`). Back that
directory up together with the database.

Prepared for a move: storage keys are backend-neutral (`<tenant>/<yyyy>/<mm>/<attachment id>`) and
every file's size and SHA-256 are in `core.attachment`. To move to another disk or a NAS:

1. `uv run heinzel files copy --to <new dir>` (resumable, verifies checksums)
2. set `HEINZEL_FILES_DIR=<new dir>`, restart the API
3. `uv run heinzel files verify`

A different backend (e.g. a self-hosted or Swiss S3-compatible store, not AWS) is one class
implementing `put/get/delete/exists/iter_keys` in `heinzel_api.files`, a new value for
`HEINZEL_STORAGE`, and the same copy/verify steps.

## Modules

A module with backend code has a package `modules/<id>/backend/` with `setup(host)`; the core
imports it as `heinzel_modules.<id>` at startup (`heinzel_api.modules`). Through the host a module
adds its router (`/api/v1/<id>`), home widgets (declared in `contributes.dashboard_widgets`) and
scheduled jobs; it registers search providers, file access checks, inbox actions and event handlers
with the core services directly. Its tables live in schema `mod_<id>` with migrations in
`backend/migrations/` and their own version table, so modules are migrated independently.

Jobs run inside each API process every few minutes (not in tests, `HEINZEL_JOBS_ENABLED=false`
turns them off); an advisory lock makes sure only one process runs a job at a time.

## Export and import

`heinzel_api.transfer` writes one `.tar.gz`: `manifest.json` (versions, migration state, a check
value of the secret key, tables and files with row counts and SHA-256), every core and module
table in PostgreSQL COPY format (`db/<schema>.<table>`, found from the catalogue in foreign-key
order, so new tables are included without changes here) and the stored files. It reads in one
repeatable-read transaction, tenant by tenant for tables under row level security, so it can run
while the portal is in use; sign-in sessions are left out.

The import checks every checksum and that the target's migrations match, then, in one
transaction, lifts forced RLS and user triggers (the audit log's append-only guard), truncates,
loads in order, resets sequences, re-encrypts secrets for the target key and restores RLS and
triggers. Files are written to storage afterwards. When you add a field encrypted with
`crypto.encrypt`, add it to `transfer.SECRETS` (or `_rekey`) so moves keep it readable.
