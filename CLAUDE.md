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
tenants/<slug>  tenant config and assets (dev seed; later stored in the database)
packages/       shared code once needed (ui, sdk)
docs/           concept snapshots
```

## Commands

```bash
docker compose up -d                       # postgres, valkey, mailpit
cd apps/api && uv sync && uv run heinzel migrate && uv run heinzel seed-tenants
uv run heinzel create-admin --tenant schmelzi --email ... --name "..."
uv run uvicorn heinzel_api.main:app --reload --port 8000
pnpm install && pnpm dev:web               # http://localhost:5173
cd apps/api && uv run pytest -q && uv run ruff check . && uv run ruff format --check .   # pytest needs Postgres
pnpm check:web && pnpm build:web
```

## Conventions

- UI copy: German (de-CH), informal "du", a verb on every action, no IT jargon.
- Swiss spelling (ss, not ß). Dates via the user's resolved preferences, never hardcoded formats.
- API: `/api/v1/...`, Pydantic models for every request and response, ISO 8601 UTC timestamps.
- Svelte: runes only (`$state`, `$derived`, `$props`), `#lib/...` imports, component-scoped CSS on tokens.
- Accessibility: real buttons/links/labels, 44 px touch targets, WCAG AA in light and dark.
- Tests next to every feature: pytest for the API, `pnpm check` must stay green.
- Database: schema `core` for the core, `mod_<id>` per module. Every tenant table gets
  `tenant_id` and `tenant_table_security()` in its migration; add an isolation test.
- Requests: `with tenant_session(db, tenant.id) as s:` per unit of work. Raise HTTP errors
  after the block when the outcome must be committed anyway (e.g. failed-login counters).
- Every write calls `audit.record(...)` in the same transaction.
- Route protection: `Depends(require("<permission>"))`; `PrincipalDep` for "signed in".

## Decisions taken during implementation

- Sessions live in Postgres (`core.session`, token hash only), not Valkey: one store, RLS, simple
  revocation. Revisit if load demands it.
- Mail is sent synchronously after commit (`heinzel_api.mail`); failures are reported (`mail_sent: false`) and
  logged. Replace with the outbox + worker when the worker exists. SMTP passwords are referenced as
  `env:VAR` in tenant.json, never stored there.
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

Next, in this order:
- [ ] Admin console, rest: Audit-Log viewer, custom roles (create/edit; step-up 2FA for role changes as in the design), Module, Einstellungen (Branding, Sprache & Region, Navigation, Anmeldung, E-Mail)
- [ ] Mein Profil: Sprache & Region with tenant defaults and locks, change password (API exists)
- [ ] Then Phase 2 engines (inbox, search, files), then the first module: Aufgaben
