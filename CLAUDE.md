# CLAUDE.md

Guidance for Claude Code in this repository. Read this first, then the concept.

## What Heinzel is

A modular, multi-tenant company portal. The core provides the shell, engines and administration;
every business feature is a small module. Stiftung Schmelzi is the first tenant; nothing in the
product may be Schmelzi-specific (branding is tenant configuration).

## Sources of truth

1. `docs/concept/core-platform.md`: technical concept (snapshot of the live doc, see `docs/README.md`).
2. `docs/concept/modules/*.md`: one spec per module, fixed format (`_template.md`).
3. Design canvas (Claude Design): https://claude.ai/artifact/PZTebzCJLQTwez8bjzeZCA
4. `tenants/<slug>/tenant.json` and `modules/<id>/heinzel.module.yaml`: the configuration contracts.

If code and concept disagree, ask before changing the concept. Do not invent features that are
not in the concept; propose them instead.

## Non-negotiables

- **Core vs. modules**: the core has no business features. A module is one feature, never a department.
- **Isolation**: a module uses only its own tables (own Postgres schema `mod_<id>`) and the core
  APIs declared in its manifest. No imports between modules.
- **Permissions**: every route and MCP tool checks a permission declared in the manifest,
  named `<module>.<object>.<action>`. Deny by default.
- **Tenant isolation**: every tenant-scoped table has `tenant_id`, enforced by Postgres RLS.
- **Tenant brand in front**: no hardcoded tenant name, logo or colour. Heinzel appears only as
  "powered by". Components use design tokens (CSS variables), never raw colours.
- **One pipeline**: UI, REST and MCP share the same schemas and the same permission checks.
- **Audit**: every write is attributable to user, tenant, channel (Web/API/MCP) and time.
- **Runtime**: all modules run in-process. No container modules.
- **Privacy**: data stays in Switzerland, revDSG. No third-party CDNs (fonts are self-hosted).

## Repository layout

```
apps/api        FastAPI core (Python 3.13, uv)
apps/web        SvelteKit 3 + Svelte 5 runes + Tailwind 4 (pnpm workspace)
modules/<id>    module manifest, settings schema, later api/ code
tenants/<slug>  seed for a new tenant: tenant.json and assets (then edited in the portal)
packages/       shared code once needed (ui, sdk)
docs/           concept snapshots
deploy/         Caddyfile for the local full stack (production proxy config follows)
scripts/dev.mjs the `pnpm dev` runner
```

## Commands

```bash
pnpm dev                                   # infra in Docker, migrate + seed, API :8000 + web :5173 with reload
pnpm stack                                 # whole stack in Docker behind Caddy on :8080
cd apps/api && uv run heinzel create-admin --tenant schmelzi --email ... --name "..."
cd apps/api && uv run pytest -q && uv run ruff check . && uv run ruff format --check .   # pytest needs Postgres
pnpm check:web && pnpm build:web
```

## Conventions

- UI copy: German (de-CH), informal "du", a verb on every action, no IT jargon.
- Swiss spelling (ss, not ß). Dates via the user's resolved preferences, never hardcoded formats.
- API: `/api/v1/...`, Pydantic models for every request and response, ISO 8601 UTC timestamps.
- Svelte: runes only (`$state`, `$derived`, `$props`), `#lib/...` imports, component-scoped CSS on tokens.
- Encrypted fields (`crypto.encrypt`) must be listed in `transfer.SECRETS` (or `_rekey`), so an import
  into an installation with another `HEINZEL_SECRET_KEY` keeps them readable.
- User text as HTML only through `renderMarkdown()` (`#lib/markdown.ts`); no other `{@html}` with user data.
- Accessibility: real buttons/links/labels, 44 px touch targets, WCAG AA in light and dark.
- Tests next to every feature: pytest for the API, `pnpm check` must stay green.
- Database: schema `core` for the core, `mod_<id>` per module. Every tenant table gets
  `tenant_id` and `tenant_table_security()` in its migration; add an isolation test.
- Requests: `with tenant_session(db, tenant.id) as s:` per unit of work. Raise HTTP errors
  after the block when the outcome must be committed anyway (e.g. failed-login counters).
- Every write calls `audit.record(...)` in the same transaction.
- Route protection: `Depends(require("<permission>"))`; `PrincipalDep` for "signed in".
- Modules: `modules/<id>/backend/` is a Python package with `setup(host)` (see `heinzel_api/modules.py`);
  routes are mounted under `/api/v1/<id>` and answer 404 while the module is off. Migrations in
  `backend/migrations/` (env.py calls `run_module_env()`), own version table in `mod_<id>`; `heinzel migrate`
  runs the core first, then every module. Keep rules in a service layer the routes, inbox actions, jobs
  and MCP tools share. Lint modules too: `uv run ruff check . ../../modules` from apps/api.

## Decisions taken during implementation

- Tenant configuration lives in the database. `heinzel seed-tenants` creates settings and assets only for new
  tenants; `--reset-config` overwrites them from `tenants/<slug>/` (discards portal changes). Domains are
  operator-managed (seed), not editable by tenant admins.
- Search: modules call `search.index()`/`search.remove()` in the same transaction as the change, set
  `permission` on each document and register `can_view` for row-level checks; never index sensitive fields.
  Manifest: `contributes.search_providers: [{type, label, icon}]`. The MCP tool `search` must use `search.run`.
- Files stay on the local machine (Docker volume / `var/files`) until a move is decided; target would be a
  self-hosted or Swiss S3-compatible store, never AWS. Back the files directory up with the database.
- Modules: deliver inbox items with `ref_type/ref_id` (re-delivery updates, `resolve()` closes); upload files with
  `?module=<id>`, then `files.link()` them to their object and register an access check for that target type.
- Module settings conventions: `quick_action_enabled`, `widget_enabled`, `search_enabled` switch the module's
  contributions off; the shell already honours `quick_action_enabled`.
- Uploaded logos get content-hashed names (cache busting) and are served with a sandbox CSP.
- Sessions live in Postgres (`core.session`, token hash only), not Valkey: one store, RLS, simple
  revocation. Revisit if load demands it.
- Mail is sent synchronously after commit (`heinzel_api.mail`); failures are reported (`mail_sent: false`) and
  logged. Replace with the outbox + worker when the worker exists. SMTP passwords are referenced as
  `env:VAR` in tenant.json, never stored there.
- Sensitive actions use `require_step_up(permission)`; the web wraps them in `withStepUp()`.
- Admins can only grant roles whose permissions they hold themselves; the last active admin cannot be
  deactivated or lose the admin role; nobody can deactivate themselves.
- Rate limiting fails open when Valkey is down (lockout still applies).
- TOTP seeds are Fernet-encrypted with a key derived from `HEINZEL_SECRET_KEY`.
- Failed logins answer identically for unknown e-mail, wrong password and locked account; the
  audit log has the real reason.
- CSRF: SameSite=Lax cookie, JSON-only bodies, and a same-origin check on writes (`main.py`).
  The reverse proxy must keep the `Host` header and set `X-Forwarded-For`; the API trusts both.

## Status and next steps (Phase 1: Foundation)

Done:
- [x] Monorepo scaffold, dev infrastructure (docker compose), CI
- [x] Tenant config loading and resolution by host name (`localhost` = Schmelzi in dev)
- [x] Module manifest validation (contract checks) and loading
- [x] `GET /api/v1/shell`: branding + navigation (top section, areas, admin) + quick actions
- [x] Web shell: sidebar from the API, tenant logo light/dark, brand colours, light/dark mode, "powered by"
- [x] Database: SQLAlchemy models + Alembic (schema `core`), runtime role `heinzel_app`, forced RLS, isolation tests
- [x] Audit log: append-only (grants + trigger), hash chain per tenant, `heinzel verify-audit`
- [x] Identity: local accounts (Argon2id), lockout, TOTP with replay protection, server-side sessions, `/me`
- [x] RBAC: permissions from core catalogue + manifests, system roles `admin` (`*`) and `staff` (manifest defaults), shell filtered
- [x] CLI: `heinzel migrate | seed-tenants | create-admin | verify-audit`
- [x] Web: login (password, TOTP, MFA enrolment with QR), protected `(app)` routes, profile card, logout
- [x] Identity, part 2: invitations, forgotten password, reset links (`/konto/<token>`), change password (API), MFA reset by admin; mail via SMTP (Mailpit in dev)
- [x] Rate limits per IP in Valkey (login, TOTP, forgot password, token links); wrong TOTP codes count toward lockout
- [x] Admin: Benutzer & Rollen (list, filter, invite, resend, roles, deactivate/activate, 2FA reset; read-only permission matrix)

- [x] Audit-Log viewer: filters in the URL (person, area, channel, period, text), day groups, details with hash, "Ältere laden", CSV export (audited), chain check shown (cached 10 min)
- [x] Mein Profil: Sprache & Region (tenant defaults and locks, preview), Darstellung (light/dark/system, per browser), Sicherheit (change password, 2FA status)
- [x] Formatting: `#lib/format.ts` `formatter(shell.user.localization)`; never format dates or numbers elsewhere

- [x] Custom roles (create, edit, delete; staff permissions editable, admin fixed) and step-up confirmation
      (`require_step_up`, `POST /auth/step-up`, 10 min) for role definitions and role assignments; web: `withStepUp()`
- [x] Manifest default permissions are applied once per tenant (`core.permission_seeded`), so seeding never undoes an admin's change

- [x] Tenant settings in the database (`core.tenant_settings`, `core.tenant_asset`, `core.tenant.domains`), runtime
      `TenantRegistry` (30 s cache, invalidated on save); `tenants/<slug>/` is only the seed
- [x] Einstellungen: Allgemein, Branding (logos upload, colours, theme, powered by), Sprache & Region (defaults + locks),
      Anmeldung and E-Mail (step-up; SMTP password encrypted, test mail); optimistic versioning

- [x] Module admin: activate/deactivate (data stays), area, sub-navigation, settings form generated from
      settings.schema.json (`x-enum-labels`, `x-group`), MCP tools/prompts per tenant; Navigation tab (areas, order,
      hide empty; areas in use cannot be removed)

Phase 1 (core platform and admin console) is complete.

- [x] Files: `heinzel_api.files` (sniffed types, size limit, clamd INSTREAM scan, local storage, staged → linked,
      module access checks via `files.register_access`), `POST/GET /api/v1/files`
- [x] Inbox: `heinzel_api.inbox.deliver/resolve/register_action`, Mein Eingang page, sidebar badge, Übersicht summary;
      core notices for accepted invitations and role changes; `heinzel demo-inbox` for sample items

- [x] File storage stays local (`HEINZEL_STORAGE=local`), prepared for a move: backend-neutral keys,
      `heinzel files verify` / `heinzel files copy --to`; no AWS. Another backend = one class in `files.py`
- [x] Search: `core.search_document` (unaccent, simple prefix + German stemming), `heinzel_api.search`
      (`index/remove/register_provider/run`), `GET /api/v1/search`, people auto-indexed, pages matched live;
      Ctrl K dialog (filter chips, keyboard, highlights); `heinzel reindex-search`
- [x] CLI refuses to run (except `migrate`) while migrations are pending

- [x] Module host: backend packages with `setup(host)`, routers per module (404 while off), module migrations
      with their own version table, in-process events (`events.publish/subscribe`, `core.user.deactivated`),
      scheduled jobs (advisory lock, `heinzel run-jobs`), home widgets (`GET /api/v1/home`)
- [x] Aufgaben (first module): personal and shared lists with members, quick add, due tags, assignment via
      Mein Eingang (action "Erledigt", notice to the creator), pictures, search, widget "Heute fällig",
      reminders (inbox or inbox + e-mail), retention, hand-back on deactivation; Übersicht redesigned
- [x] Aufgaben: checklists (tick, rename, reorder by drag or Alt+↑/↓, progress in the line and inbox) and
      attachments of all common formats (files service: pictures, PDF, OOXML, ODF, TXT/CSV; no macros, no archives)
- [x] Production stack `compose.prod.yml` (Caddy HTTPS, ClamAV, daily backup container) and `deploy/heinzel.sh`;
      `heinzel export` / `heinzel import` move all data and files between installations (`heinzel_api.transfer`)
- [x] Notes with simple Markdown: `#lib/markdown.ts` (escapes first, then a fixed subset; safe for `{@html}`) and
      `#lib/components/MarkdownNote.svelte` (formatted view, growing editor, toolbar); inbox bodies render it too

Next, in this order:
- [ ] MCP gateway (tools from manifests, respects permissions and `mcp_disabled`)
