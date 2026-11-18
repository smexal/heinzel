# Heinzel: Technical Documentation

Nov 17, 2026 · @Silas

## Purpose and scope

Heinzel is a modular, multi-tenant cloud portal: one central place where staff find their tools, submit requests and get administrative work done. Stiftung Schmelzi is the first tenant. Branding is configuration, so nothing in the product is Schmelzi-specific.

**Goals**

- One entry point for staff: tools, requests, orders and company information.
- Replace custom Excel tools with forms, workflows and list views on shared core services.
- Let new tools be added as isolated modules that follow a defined contract.
- Serve multiple organisations from one codebase, each with its own branding, modules and data.

**Non-goals (v1)**

- Not a full ERP, HR or accounting system. Heinzel does not replace them.
- Not a document management system. Heinzel stores attachments only.
- No third-party module marketplace. Modules are developed by the platform team. No native desktop or mobile apps yet: v1 is a responsive web app, prepared for apps later (see Clients).

**Out of scope for now** (specified later): all modules except the first one (Aufgaben), and all integrations with other systems such as Microsoft 365 (Entra ID login, mail, Teams), SharePoint and CGM TOPSOZ. The core is designed so both can be added without changes to it.

**Users and roles**

| Group | Typical use |
| --- | --- |
| Staff | Submit requests, create Unterhalt orders, reserve rooms and vehicles, look up contacts |
| Verwaltung / Sekretariat | Process requests, manage master data, Posteingang, templates |
| Unterhalt | Receive, plan and close orders |
| Approvers (Bereichsleitung, GL) | Approve requests in workflows |
| Tenant admin | Users, roles, modules, branding for one tenant |
| Platform operator | Tenants, deployments, monitoring across all tenants |

## Guiding principles and non-functional requirements

The core does the hard, shared things once; modules stay small and only describe their domain.

**Principles**

1. **Core is the frame, modules are the work.** The core provides the shell, the engines (identity, permissions, forms, workflow, work items, collections, inbox, notifications, audit) and administration. Every user-facing business feature, such as Anträge, Störungsmeldungen or Listen, is a module.
2. **One module, one feature.** Modules are small. A department is a navigation area that groups modules, never a module itself.
3. **Configuration over code.** Branding, navigation areas, forms, workflow steps and module activation are tenant configuration wherever possible.
4. **Isolation by default.** A module sees only its own data and the core APIs it declared in its manifest.
5. **Tenant brand in front.** The tenant's logo, colours and name lead every screen. Heinzel appears only as a small "powered by" mark and a faint background element. No tenant name, logo, colour or text is hardcoded.
6. **AI-ready by design.** Every capability is exposed via MCP with the same permissions as the UI. API-first: the UI, REST and MCP share one schema.
7. **Boring technology.** Proven, self-hostable components the team already knows.
8. **Everything audited.** Every write is attributable to a user, tenant, client (UI, API, MCP) and timestamp.

**Non-functional requirements**

| Area | Requirement |
| --- | --- |
| Hosting | Data stored in Switzerland |
| Privacy | Compliant with the Swiss revDSG |
| Availability | Business hours critical; target 99.5% monthly |
| Performance | Page loads under 1 s for typical list and form views |
| Languages | de-CH first; fr-CH and en prepared via i18n from day one |
| Accessibility | WCAG 2.1 AA for core UI |
| Devices | Desktop first; fully usable on tablet and phone (Unterhalt in the field) |
| Backup | Daily, encrypted, 30-day retention, restore tested quarterly |

## Architecture overview

&#91;embedded content: Heinzel architecture: clients, gateway, core, modules, data\]

Web UI, REST and MCP clients all pass the same gateway, so tenant resolution and permission checks happen once. Modules sit beside the core and reach data and other services only through the core SDK and events.

## Multi-tenancy and branding

All tenants share one database. Every row carries a `tenant_id`, and PostgreSQL Row-Level Security (RLS) enforces isolation, so a missing filter in code cannot leak data.

**Isolation model**

| Level | Mechanism |
| --- | --- |
| Request | Tenant resolved from the hostname (`h``einz``el``.schmelzi.ch` maps to tenant `schmelzi`) and bound to the session |
| Database | `tenant_id` column on every tenant-scoped table; RLS policy `tenant_id = current_setting('app.tenant_id')` |
| Files | Object storage prefix per tenant: `/{tenant_id}/{module}/...` |
| Identity | Local user store per tenant; optional external providers (e.g. Entra ID) configured per tenant |
| Escalation path | A tenant that needs hard isolation gets its own deployment and database from the same images, without code changes |

**Tenant configuration**

Stored in the `tenant` table as validated JSON and editable by the tenant admin in the UI. Example:

```json
{
  "slug": "schmelzi",
  "domains": ["heinzel.schmelzi.ch"],
  "display_name": "Stiftung Schmelzi",
  "short_name": "Schmelzi",
  "branding": {
    "logo_light": "assets/logo-schmelzi.svg",
    "logo_dark": "assets/logo-schmelzi-dark.svg",
    "logo_mark": "assets/mark-schmelzi.svg",
    "colors": { "primary": "#3B7084", "accent": "#BDCF1F" },
    "theme_default": "system",
    "powered_by": true
  },
  "legal": { "imprint_url": "…", "privacy_url": "…" },
  "localization": {
    "languages": ["de-CH"],
    "defaults": {
      "language": "de-CH",
      "timezone": "Europe/Zurich",
      "date_format": "dd.MM.yyyy",
      "time_format": "24h",
      "first_day_of_week": "monday",
      "number_format": "1'234.50",
      "currency": "CHF"
    },
    "locked": ["timezone", "currency"]
  },
  "navigation": {
    "hide_empty_areas": true,
    "areas": [
      { "key": "unterhalt", "label": { "de": "Unterhalt" }, "order": 10 },
      { "key": "verwaltung", "label": { "de": "Verwaltung" }, "order": 20 },
      { "key": "it", "label": { "de": "IT" }, "order": 30 }
    ]
  },
  "identity": {
    "local": {
      "enabled": true,
      "mfa_required": "all",
      "password_min_length": 12,
      "self_service_reset": true,
      "lockout": { "attempts": 5, "minutes": 15 },
      "session_idle_hours": 8
    },
    "providers": [
      { "type": "entra", "enabled": false, "tenant_id": "…", "client_id": "…", "jit_provisioning": true }
    ]
  },
  "email": {
    "from_name": "Stiftung Schmelzi",
    "from_address": "heinzel@schmelzi.ch",
    "reply_to": "it@schmelzi.ch",
    "smtp": { "host": "…", "port": 587, "security": "starttls", "username": "heinzel@schmelzi.ch", "password_ref": "secret://email/smtp" }
  },
  "modules": [
    { "key": "aufgaben", "enabled": true, "area": null, "hidden_children": [] },
    { "key": "stoerungen", "enabled": true, "area": "unterhalt", "hidden_children": [] }
  ]
}
```

- **Brand placement**: the tenant logo sits top left in the sidebar and links to the Übersicht; the login shows the tenant logo and name. Heinzel appears only as "powered by Heinzel" in the sidebar and login footer, plus a faint background mark on the login. `powered_by` can be switched off.
- **Colours**: the tenant sets only `primary` and `accent`. Heinzel derives the full token set (tints, hover, text on tint, borders) for light and dark mode and checks contrast against WCAG AA. Status colours (warning, danger, info, success) stay semantic and are not brandable. Components use tokens only, never raw colour values.
- **Light and dark mode**: each user chooses light, dark or system in the sidebar; the tenant sets the default (`theme_default`). A tenant supplies `logo_dark` for dark backgrounds; without it, the logo is shown on a light plate.
- **Navigation areas**: the tenant defines the sidebar areas (e.g. Unterhalt, Verwaltung, IT); modules are assigned to an area.
- Secrets (client secrets, API keys) are stored encrypted in a separate secrets store, never in this JSON.
- UI texts are i18n keys. A tenant may override individual strings (e.g. "Unterhalt" vs "Hauswartung").

**Where each part is edited**

| Admin screen | Config keys | Notes |
| --- | --- | --- |
| Einstellungen › Branding | `display_name`, `short_name`, `branding.*`, `legal.*` | `logo_mark` also serves as favicon and app icon; `domains` shown read-only |
| Einstellungen › Sprache & Region | `localization.*` | Lock switch per setting writes `locked` |
| Einstellungen › Navigation | `navigation.*` | Areas, order, hide empty areas |
| Einstellungen › Anmeldung | `identity.*` | External providers later |
| Einstellungen › E-Mail | `email.*` | SMTP password goes to the secrets store, the config holds only `password_ref`; templates are stored per language in the database |
| Module › (module) | `modules[]` and the module's own settings | `area` and `hidden_children` set the module's place in the sidebar |
| Plattform-Betrieb | `slug`, `domains` | Only the platform operator; needs DNS and TLS |

## Core services

The core provides the shell, the engines and administration, but no business features of its own. Everything a user does for their work (Anträge, Störungsmeldungen, Listen) is a module built on the engines. Every service is also exposed through the MCP gateway (see AI readiness).

| Service | Responsibility | Key capabilities |
| --- | --- | --- |
| Identity | Login and sessions | Local accounts first (user management, password, TOTP MFA, reset); pluggable external providers such as Entra ID; account linking; tenant-bound sessions |
| Permissions (RBAC) | Who may do what | Roles per tenant; permissions declared by modules (`stoerungen.report.create`); optional role-to-group mapping from external providers; scoping by site/department |
| Shell and navigation | The frame every screen lives in | Tenant branding, sidebar with core entries, tenant-defined areas, module entries with sub-navigation, search entry (Ctrl K) at the top of the sidebar, light/dark switch, "powered by" footer |
| Home (Übersicht) | Personal start page | Greeting, quick actions and widgets contributed by modules, summary of open inbox tasks |
| Inbox (Mein Eingang) | One place for everything that needs me | Tasks and notices delivered by modules and administration; unread state; the reason it was routed to me; actions supplied by the sending module; filter by source; link back into the module |
| Forms engine | Structured data capture | Form definitions as JSON Schema + UI schema; versioned; validation in browser and API; file fields |
| Workflow engine | Approvals and states | State machines per type; approval steps by role or person; delegation and substitution; SLAs and reminders |
| Work items engine | Things with a lifecycle | Status, assignee, priority, location, due date, comments, history; used by modules such as Störungsmeldungen |
| Collections engine | Tables that replace Excel | Typed records on a form definition; list views with filters, inline edit and export |
| Notifications | Telling people | Email (SMTP), in-app; per-user preferences; templates per tenant and language; further channels later |
| Audit log | Traceability | Append-only record of every write and permission change, with channel (Web, API, MCP) and acting client |
| Files | Attachments | S3-compatible object storage per tenant; virus scan on upload; signed download links |
| Directory | People and organisation | Users, departments, sites, locations (building, room); the shared master data modules reference |

**Authentication: local first, providers pluggable**

Heinzel works standalone with its own user management. External identity providers plug in per tenant through configuration, without code changes.

- **v1, local accounts**: tenant admin invites users by email, deactivates them and resets MFA. Users set their own password, enrol TOTP and reset forgotten passwords themselves. Argon2id hashing, length-based password policy, lockout and rate limiting on login.
- **Provider abstraction**: an `AuthProvider` interface with implementations `local`, `oidc` (Entra ID first, any OIDC provider works) and `saml` (later). The login screen shows the providers enabled for the tenant.
- **Account linking**: an external identity links to an existing local user via verified email. The admin decides whether password login stays allowed for linked users.
- **Provisioning**: optional just-in-time user creation and group sync on login; SCIM later.
- **One token model**: whatever the login method, Heinzel issues its own sessions and tokens. Modules, REST and MCP never know or care how the user logged in. Heinzel is the OAuth 2.1 authorization server for API and MCP clients.

**Personal settings and localization**

Every user sets their language and regional formats in "Mein Profil". The tenant sets the defaults in Einstellungen and decides per setting whether users may change it.

| Setting | Options | Tenant default (Schmelzi) |
| --- | --- | --- |
| Language | Only languages the tenant enables (de-CH, fr-CH, en) | de-CH |
| Time zone | IANA time zones | Europe/Zurich (locked) |
| Date format | 17.11.2026 · 2026-11-17 · 17/11/2026 · 11/17/2026 | 17.11.2026 |
| Time format | 24 h (14:24) · 12 h (2:24 PM) | 24 h |
| First day of week | Monday · Sunday · Saturday | Monday |
| Number format | 1'234.50 · 1.234,50 · 1,234.50 · 1 234,50 | 1'234.50 |
| Currency | CHF · EUR (display in modules) | CHF (locked) |
| Theme | Light · dark · system | System |

- **Resolution order**: user setting, then tenant default, then platform default (de-CH). A setting left on "Standard" follows later changes of the tenant default.
- **Locking**: a locked setting is shown read-only in the profile and applies to everyone.
- **One formatting path**: the API returns ISO 8601 timestamps (UTC) and raw numbers; clients format them with the resolved preferences via the Intl APIs. Emails, PDFs and exports are formatted server-side with the same resolved values.
- **Available everywhere**: `GET /me/preferences` returns the resolved values and their source (user or tenant); MCP exposes them as `heinzel://me/preferences`, so AI clients answer in the user's formats.

**Engines versus modules**

Engines have no menu entries of their own; modules turn them into features:

- *Berechtigungsantrag* (module) = a form "which system, which access, why" + a workflow "line manager approves, IT executes, requester is notified" on the forms and workflow engines.
- *Störungsmeldungen* (module) = a work item type with a form (location, description, photos, urgency), its own board, list and "my reports" views, and a quick action on the home page.
- An Excel tool becomes a small *Listen* module, or a collection the tenant admin configures without code.

**Global search**

One search entry at the top of the sidebar (Ctrl K) opens a search dialog. It searches core data and every active module and shows results grouped by entity type, with filter chips per group, keyboard navigation and highlighted matches.

- **Providers**: each module declares `search_providers` in its manifest (entity type, label, icon, indexed fields, result line). The core provides people, places and admin pages.
- **Index**: a central `search_document` table (tenant, module, entity type, entity id, title, text, tsvector with unaccent and German/French configuration), kept current from module events. PostgreSQL full-text search in v1.
- **Permissions, twice**: the index query only covers modules the user may use; then each provider's `can_view(entity_ids, user)` checks every hit before it is shown. Hidden hits are never counted or hinted at, snippets come only from fields the user may see, and sensitive fields are never indexed.
- **One pipeline**: the dialog, `GET /search` and the MCP tool `search` all use the same filtering.

## Administration console

Everything a tenant needs to run Heinzel is managed in the browser by an admin user: users, roles, permissions, modules, settings and the audit log. No config files, no CLI and no redeploy are needed for day-to-day administration.

**Admin roles**

| Role | Scope | Can |
| --- | --- | --- |
| Tenant admin | One tenant | Everything in the admin areas below for their own tenant |
| User admin (delegated) | One tenant, optionally limited to a site or department | Invite, edit and deactivate users; assign roles within their scope |
| Auditor | One tenant | Read and export the audit log; no changes |
| Platform operator | All tenants | Create and suspend tenants, manage domains and module versions, monitor health; no access to tenant content by default |

**Admin areas**

| Area | What an admin can do |
| --- | --- |
| Users | Invite by email, edit, deactivate, unlock, reset password and MFA, link external identities, view a user's effective permissions |
| Roles and permissions | Create custom roles, permission matrix grouped by module, scope roles to site or department, map groups from external providers |
| Modules | Enable or disable per tenant, assign the navigation area, show or hide sub-navigation entries, module settings (form generated from the module's `settings_schema`), default role mapping, MCP tool toggles, installed version |
| Request and order types | Configure types, build forms, define workflow steps and approvers |
| Tenant settings | Branding and legal links, domains (read-only, set by the platform operator), navigation areas, localization defaults and locks (languages, time zone, date and time format, first day of week, number format, currency), login providers, email, retention periods |
| AI / MCP | Connected clients, active tokens, enabled tools, revoke access |
| Audit log | Search and filter by user, module, action, target and time; before/after diff per change; export CSV |

**Rules**

- The admin console is itself a core module and uses the same permission system (`admin.users.manage`, `admin.roles.manage`, `admin.modules.manage`, `admin.settings.manage`, `admin.audit.read`), so admin rights can be split across people.
- Every admin action is also available through REST and MCP, with confirmation for destructive actions.
- Sensitive actions (role changes, MFA reset, disabling a module, changing login providers) require re-authentication with MFA.
- The last tenant admin cannot be removed or deactivated.
- Permission changes take effect immediately; cached permissions are invalidated on change.
- Admin actions are audited like everything else, including who viewed the audit log and what was exported.
- Audit entries are hash-chained, so a deleted or altered entry is detectable. Retention is configurable per tenant.
- Platform operator access to tenant content is break-glass only: time-limited, with a stated reason, and visible to the tenant admin in their audit log.

**First admin**

When a tenant is created, the platform operator enters the first admin's email. That person receives an invitation link, sets a password and MFA, and from then on manages the tenant alone.

## Module contract

A module is a self-contained package with a manifest, a backend part, a frontend part and its own database schema. It may only use what its manifest declares.

**Manifest (`heinzel.module.yaml`)**

```yaml
id: stoerungen
name: { de: Störungsmeldungen, en: Fault reports }
version: 1.2.0
core_api: ">=1.0 <2.0"
runtime: in-process            # the only runtime
permissions:
  - id: stoerungen.report.create
    label: { de: Störung melden }
    default_roles: [staff]
  - id: stoerungen.report.manage
    label: { de: Meldungen bearbeiten }
    default_roles: [unterhalt]
uses_core: [identity, permissions, forms, workflow, orders, notifications, files, directory]
navigation:
  default_area: unterhalt         # tenant admin can move it to another area
  entry: { label: { de: Störungsmeldungen }, path: /stoerungen, icon: wrench, permission: stoerungen.report.create }
  children:                       # sub-navigation, shown when the module is open
    - { label: { de: Board }, path: /stoerungen/board, permission: stoerungen.report.manage }
    - { label: { de: Liste }, path: /stoerungen/liste, permission: stoerungen.report.manage }
    - { label: { de: Meine Meldungen }, path: /stoerungen/meine, permission: stoerungen.report.create }
contributes:
  order_types: [stoerungsmeldung]
  dashboard_widgets: [my-open-reports]
  quick_actions: [stoerung-melden]
  search_providers: [reports]
  notification_templates: [report-assigned, report-done]
events:
  publishes: [stoerungen.report.closed]
  subscribes: [directory.location.changed]
settings_schema: settings.schema.json   # tenant-level module settings
mcp:
  tools:
    - name: stoerungen.report.create
      permission: stoerungen.report.create
      description: { en: Report a fault at a location }
      annotations: { readOnlyHint: false, idempotentHint: true }
    - name: stoerungen.report.list_mine
      permission: stoerungen.report.create
      annotations: { readOnlyHint: true }
  resources: ["heinzel://stoerungen/reports/{id}"]
  prompts: [stoerung-melden]
```

**Granularity and navigation**

- **One module, one feature.** A module covers a single job, such as Störungsmeldungen, Schlüsselausgabe or Sitzungszimmer buchen. It never covers a whole department.
- **Areas group modules.** A department such as Unterhalt, Verwaltung or IT is a navigation area, defined per tenant (name, order, icon). Each module declares a `default_area`; the tenant admin can move it to another area, or into the top section next to Übersicht and Mein Eingang (area: null) for features everyone uses, such as Aufgaben.
- **Sub-navigation.** A module may declare `children`. They show below the module entry while the module is open, each guarded by its own permission. The tenant admin can hide individual children.
- **Small modules stay small.** If a module needs more than about five sub-navigation entries, it is probably two modules.

**Isolation rules**

| Rule | Enforcement |
| --- | --- |
| Own data only | Each module gets its own Postgres schema (`mod_unterhalt`) and DB role with grants on that schema only; RLS by tenant |
| Core via API only | Modules call the core SDK, never core tables directly |
| No module-to-module imports | Cross-module communication only via events or published APIs; checked in CI |
| Declared permissions only | Every route and action checks a permission from its own manifest |
| Own UI area | Frontend lives under its own route group and uses the shared design system components |
| Versioned contract | `core_api` range checked at install; breaking core changes require a major version |

**Runtime**

All modules run in-process: the backend is a FastAPI router mounted by the core, the frontend a route group in the SvelteKit app. There is no container mode. Existing tools such as the Logalyzer are rebuilt as modules on the core, not wrapped or ported as separate services.

**Lifecycle**

1. **Install**: register manifest, run the module's migrations, create permissions.
2. **Enable per tenant**: tenant admin activates it, maps roles, fills module settings.
3. **Disable**: hidden and inaccessible, data retained.
4. **Uninstall per tenant**: data exported, then deleted after a retention period.

**Extension points a module can contribute**

Navigation entry with sub-navigation, quick actions, dashboard widgets, inbox items (tasks and notices with their actions), request types, work item types, collections (form + list), notification templates, scheduled jobs, event handlers, global search providers.

## AI readiness (MCP)

Everything a user can do in the UI, an AI client can do through MCP, as that user and with exactly that user's permissions. MCP is a core interface next to the web UI and the REST API, not an add-on.

**Heinzel MCP server**

| Aspect | Design |
| --- | --- |
| Endpoint | One per tenant: `https://<tenant-domain>/mcp`, Streamable HTTP transport |
| Auth | OAuth 2.1 per the MCP authorization spec; Heinzel is the authorization server; the user logs in with the tenant's method (local or an external provider such as Entra ID); tokens carry tenant, user and granted scopes |
| Identity | AI acts on behalf of the user, never as a super-user; RBAC and RLS apply unchanged |
| Implementation | Official MCP Python SDK mounted in the FastAPI app; tools generated from the same Pydantic schemas as the REST API |
| Discovery | Only tools of modules enabled for the tenant and permitted for the user are listed |
| Clients | Claude (desktop, web, Teams), Claude Code, other MCP clients, internal agents |

**What gets exposed**

- **Tools**: actions such as `orders.create`, `requests.submit`, `requests.approve`, `directory.search`, `reservations.book`. Each tool maps to one permission.
- **Resources**: read-only context such as `heinzel://orders/{id}`, `heinzel://forms/{key}` (so an AI knows which fields a form needs), `heinzel://me/inbox`.
- **Prompts**: guided tasks such as "Unterhaltsauftrag erfassen" or "Meine offenen Genehmigungen".

**Module contract addition**

Modules declare their MCP surface in the manifest (`mcp:` block): tools with permission, description and read/write annotations, plus resources and prompts. CI rejects a write route without either a matching MCP tool or an explicit `mcp: excluded` reason.

**Guardrails**

| Risk | Measure |
| --- | --- |
| AI does something unintended | Tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`); destructive or approval actions require user confirmation in the client |
| Duplicate actions on retries | Idempotency keys on all write tools |
| Untraceable changes | Audit records the actor as "user X via MCP client Y" |
| Data leakage | Sensitive fields excluded from tool output by default; tenant admin can disable MCP per module or tool |
| Abuse | Rate limits per user and client; token lifetime and revocation in admin UI |

**Designing for AI from day one**

- Every entity, form field and status has a clear description text; these become tool and schema descriptions.
- Errors are structured (`code`, `message`, `field`) so an AI can correct and retry.
- Stable, human-readable keys (`unterhaltsauftrag`, `order.status.done`) next to UUIDs.
- Global search is a core API, available to both UI and MCP.

**Later: AI inside Heinzel**

Optional features such as summarising a request thread, classifying incoming orders or suggesting an assignee use a pluggable LLM provider per tenant, configurable and off by default, with the provider's data location stated in the tenant config.

**Roadmap fit**: read-only MCP tools ship with phase 2, write tools with confirmation in phase 3.

## Clients: web first, apps later

v1 ships only the web app, responsive for desktop, tablet and phone. These decisions keep desktop and mobile apps a later addition that needs no change to the core.

| Topic | Decision now |
| --- | --- |
| API | Every UI function goes through the versioned REST API; SvelteKit pages hold no business logic an app could not reach |
| Authentication | OAuth 2.1 authorization code with PKCE and refresh tokens from day one (MCP needs it too); the web app may use secure cookies, apps use tokens |
| Tenant discovery | `/.well-known/heinzel` returns tenant branding, auth endpoints and API version, so an app can connect from a tenant URL or email domain |
| Branding and language | Design tokens, logos, translations and resolved user preferences are served as JSON, so apps render the same look and formats |
| Notifications | Channel abstraction in the notification service; push (APNs, FCM) is a later channel |
| Offline | Not in v1. Forms keep server-side drafts, the basis for offline capture later |
| Deep links | Every object has a stable URL (e.g. `/stoerungen/ST-0417`) that also works as an app deep link |
| Files | Resumable, chunked uploads (photos from a phone camera) |
| Versioning | Clients send their version; the server can require a minimum version |

Path when apps are needed: first an installable web app (PWA), then desktop and mobile shells that reuse the SvelteKit UI (e.g. Tauri for desktop, Capacitor for mobile). Fully native apps only if a real need appears; decided at that point.

## Core data model

The core schema holds tenants, people, permissions and the generic work objects (requests, orders, collections). Modules reference these by ID and keep their own tables in their own schema.

| Entity | Key fields | Relations |
| --- | --- | --- |
| `tenant` | slug, display\_name, config (JSON), status | Root of everything tenant-scoped |
| `user` | email, name, password\_hash (nullable), mfa\_secret (encrypted), locale, active | Belongs to tenant; external logins in user\_identity (provider, subject); member of departments; has roles |
| `department` | name, parent\_id, cost\_center | Tree; users belong to one or more |
| `site` | name, address | Has buildings |
| `location` | site\_id, building, floor, room, type | Referenced by orders and reservations |
| `role` | key, name, external\_group\_id | Has permissions; assigned to users or Entra groups |
| `permission` | key (e.g. `unterhalt.order.create`), module\_id | Declared by module manifests |
| `role_assignment` | user\_id or group, role\_id, scope (site/department, optional) | Scoped RBAC |
| `module_install` | module\_id, version, enabled, settings (JSON) | One row per tenant and module |
| `form_definition` | key, version, json\_schema, ui\_schema | Used by request types, order types, collections |
| `request_type` | key, form\_definition\_id, workflow\_definition | Configurable Antrag types |
| `request` | type\_id, requester\_id, data (JSON), state, created\_at | Has workflow steps, comments, attachments |
| `workflow_step` | request\_id, step\_key, assignee, decision, decided\_at | Approval history |
| `order_type` | key, form\_definition\_id, queue | E.g. Unterhaltsauftrag, IT-Auftrag |
| `order` | type\_id, title, data (JSON), status, priority, assignee\_id, location\_id, due\_at | Comments, attachments, links to requests |
| `collection` / `record` | key, form\_definition\_id / data (JSON) | Excel replacements: generic typed lists |
| `comment` | target (type, id), author\_id, body | On requests, orders, records |
| `attachment` | target, storage\_key, filename, size, scanned | Files service |
| `notification` | user\_id, channel, template, payload, read\_at | In-app inbox and delivery log |
| `audit_event` | actor\_id, client (UI/API/MCP), action, target, before/after, ip, at, prev\_hash, hash | Append-only, partitioned by month |

All tenant-scoped tables carry `tenant_id`, `created_at`, `created_by`, `updated_at`, `updated_by`. IDs are UUIDs (random v4 in Phase 1; time-ordered v7 once the API runs on Python 3.14). Added after the design session: nav\_area (key, label, order, icon) for tenant navigation areas, inbox\_item (user, source module, kind task or notice, title, routing reason, actions, read\_at, done\_at) and user\_pref (theme, language, timezone, date format, time format, first day of week, number format; empty means tenant default).

## Implementation notes (Phase 1)

The database, audit log, local login with TOTP, the protected web shell, invitations, password reset, Benutzer & Rollen, the Audit-Log viewer and Mein Profil are built. Where the build refines the model above, this table records how.

| Topic | Concept above | As built |
| --- | --- | --- |
| Schema | Core tables in one schema | Schema `core`; modules get `mod_<id>`. Migrations via Alembic, run as the schema owner (`heinzel migrate`) |
| Database roles | RLS on `tenant_id` | The API connects as `heinzel_app` (no superuser, no BYPASSRLS, owns nothing). RLS is enabled and forced on every tenant table; each transaction sets `app.tenant_id` locally. Migrations call `tenant_table_security()` for new tables |
| Tenant registry | `tenant` with config JSON | `core.tenant` holds slug, name, status and domains (operator-managed, read-only for `heinzel_app`). The configuration lives in `core.tenant_settings` (JSON, versioned, RLS) and logos in `core.tenant_asset`; admins edit them under Einstellungen. `tenants/<slug>/` only seeds a new tenant (`heinzel seed-tenants`, `--reset-config` to start over). A registry resolves the host to the tenant and caches settings for 30 seconds, invalidated on save. Sign-in and e-mail settings need a step-up; the SMTP password is stored encrypted and never shown. Uploaded logos get content-hashed names and are served with a sandbox CSP |
| `user` | email, name, password\_hash, mfa\_secret, locale, active | Table `app_user`: unique per tenant on lower(email), status (invited, active, deactivated), failed\_logins, locked\_until, mfa\_enabled, mfa\_last\_step (TOTP replay guard), preferences (JSON, replaces a separate user\_pref table), last\_login\_at |
| `permission` | Table of permission keys | No table: the catalogue is the core permissions (`core.users.manage`, `core.roles.manage`, `core.modules.manage`, `core.settings.manage`, `core.audit.read`) plus every module manifest. `role_permission` stores the keys per role |
| System roles | Roles per tenant | Two system roles per tenant: `admin` holds the wildcard `*`; `staff` gets each module permission whose manifest lists `staff` in `default_roles` |
| Sessions | Valkey | Table `core.session` in Postgres: SHA-256 of the cookie token, mfa\_passed, idle expiry (tenant `session_idle_hours`) and a 7-day absolute limit. Token rotates once the second factor is passed |
| `audit_event` | actor, client, action, target, before/after, prev\_hash, hash; partitioned by month | Fields: actor\_user\_id, channel (web, api, mcp, system, cli), action, target\_type, target\_id, data (JSON), ip. Insert-only for `heinzel_app`, a trigger blocks UPDATE, DELETE and TRUNCATE for everyone. SHA-256 chain per tenant, serialised by an advisory lock; `heinzel verify-audit` checks it. Before/after values and monthly partitions follow with the first module writes |
| MFA policy | TOTP enforceable per role | Tenant setting `mfa_required`: all, admins or optional. Seeds are Fernet-encrypted with a key derived from `HEINZEL_SECRET_KEY`; first login enrols via QR code |
| Failed logins | Lockout and rate limiting | Lockout per tenant policy (Schmelzi: 5 attempts, 15 minutes). Unknown e-mail, wrong password and locked account get the same answer; the audit log keeps the real reason. Rate limits per IP in Valkey cover login, TOTP, forgotten password and links; they fail open if Valkey is down. Wrong TOTP codes count toward the lockout |
| CSRF | Not specified | SameSite=Lax cookie, JSON-only bodies, and writes are refused when `Origin` does not match the host |
| Shell | Navigation by tenant config | `GET /api/v1/shell` returns branding to anyone (the login page needs it); navigation and quick actions only for a signed-in user, filtered by permission |
| Tenant onboarding | `heinzel tenant create` | For now `heinzel seed-tenants` registers the `tenants/<slug>` folders and creates the system roles; `heinzel create-admin` creates the first administrator |
| Invitations and reset | Admin invites by e-mail; users reset forgotten passwords themselves | Table core.action\_token (SHA-256 of the link token, purpose invite or password\_reset, single use). Invitation links last 7 days, reset links 1 hour; a new link replaces the open one. Both open /konto/\<token>. Setting the password activates invited users and ends all sessions. "Forgot password" always answers the same, whether or not the address exists |
| E-mail | SMTP, templates per tenant and language; delivery through the outbox | SMTP from tenant.json, sent right after the commit; a failure is shown to the admin (mail\_sent false) and never rolls back the change. Passwords are referenced as env:VARIABLE. German plain-text templates in code for now; outbox, retries and tenant templates follow with the worker |
| Granting roles | Admin assigns roles | Only roles whose permissions the admin holds can be granted. The last active admin cannot be deactivated or lose the admin role, and nobody can deactivate themselves. Deactivating ends all sessions; an MFA reset ends them and forces a new enrolment. Custom roles can be created, edited and deleted (only when nobody holds them); staff permissions are editable, admin is fixed. Role definitions and assignments need a step-up: a fresh TOTP code (or the password without 2FA), valid 10 minutes per session (session.step\_up\_at). Manifest default permissions are applied once per tenant (core.permission\_seeded), so a later seed never undoes an admin's removal |
| Personal settings | user\_pref table; GET /me/preferences; MCP resource heinzel://me/preferences | Stored in app\_user.preferences (JSON, key localization). GET/PUT /api/v1/me/preferences returns own values, tenant defaults, locks and options; a locked setting is refused. The shell carries the effective values, and the web formats every date and number through one formatter. Theme is stored per browser, not per user. The MCP resource follows with the MCP gateway |
| Audit viewer | Admins export per user for information requests | Filters for person, area (platform or module, by action prefix), channel, period and free text; paging by event id. CSV export with the same filters, itself recorded as audit.exported. The chain check runs on page load at most every 10 minutes per tenant; a scheduled check follows with the worker |

The reverse proxy must keep the `Host` header and set `X-Forwarded-For`: the API resolves the tenant from the host and logs the client address from that header.

## Tech stack

SvelteKit in front, FastAPI behind, PostgreSQL at the centre. Everything runs as Docker containers and stays portable between providers.

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | SvelteKit (TypeScript), Tailwind with design tokens, shadcn-svelte components | Known stack; tokens make tenant branding trivial |
| i18n | Paraglide (SvelteKit), Babel/gettext (backend) | Type-safe keys; tenant string overrides |
| Backend | Python 3.13, FastAPI, Pydantic v2 | Known stack; OpenAPI generated for free |
| ORM / migrations | SQLAlchemy 2, Alembic (one migration chain per module) | Mature; supports schema-per-module |
| Database | PostgreSQL 17 with RLS | Tenant isolation in the database itself |
| Jobs and events | Transactional outbox in Postgres + worker process | No extra broker for v1; reliable delivery |
| Cache | Valkey (Redis-compatible) | Rate limits and short-lived cache; sessions live in Postgres (see Implementation notes) |
| Object storage | S3-compatible, Swiss region | Attachments per tenant prefix |
| Auth | Own auth: Argon2id (argon2-cffi), TOTP (pyotp); external OIDC via Authlib, SAML later | Works standalone; Entra ID plugs in by configuration |
| Email / Teams | SMTP | Invites and password reset need mail from day one; no dependency on M365 |
| Forms | JSON Schema + UI schema, own Svelte renderer | Same definition validates in browser and API |
| Workflow | Own lightweight state machine (definitions in JSON) | Approvals don't need a BPMN engine |
| Reverse proxy | nginx or Caddy (TLS, per-tenant domains) | Caddy simplifies automatic certificates for many domains |
| Observability | OpenTelemetry, Prometheus, Grafana, Loki | Standard, self-hostable |
| Repo | Monorepo: `apps/web`, `apps/api`, `modules/*`, `packages/sdk`, `packages/ui`; uv + pnpm | One place for core and modules; shared CI |

## Security, privacy and compliance

Heinzel will hold personal data of staff and possibly of clients (Bewohnende, Mitarbeitende im Atelier), so revDSG compliance and Swiss data residency are requirements, not options.

| Topic | Measure |
| --- | --- |
| Data residency | Hosting, database, backups and object storage in Switzerland |
| Authentication | Local accounts with Argon2id hashing, TOTP MFA (enforceable per role), lockout; external providers apply their own MFA policy |
| Authorisation | Deny by default; every API route declares its permission; RLS as a second line |
| Encryption | TLS 1.2+ everywhere; encryption at rest for DB, backups and files; secrets in a vault, not in env files in git |
| Sensitive data | Modules flag sensitive fields in their schema; those are masked in lists, excluded from search and logged on access |
| Audit | Append-only audit log; admins can export per user for information requests (Auskunftsrecht) |
| Retention | Retention period per collection/request type; automatic deletion or anonymisation |
| Records of processing | Each module documents purpose, data categories and retention in its manifest; Heinzel generates the processing register (Verzeichnis der Bearbeitungstätigkeiten) from it |
| Dependencies | Automated dependency and container scanning in CI |
| Testing | Tenant-isolation test suite runs on every build (user of tenant A must never see tenant B) |

Open point: whether client data (health, social) is in scope for v1. If yes, a DSFA (data protection impact assessment) is needed before go-live.

## Deployment and operations

v1 runs as Docker Compose on Swiss cloud VMs; the same images can move to Kubernetes later without code changes.

**Environments**

| Environment | Purpose | Data |
| --- | --- | --- |
| local | Development via `docker compose up` | Seed data |
| staging | Acceptance, demo tenant | Anonymised copy |
| production | All live tenants | Live |

**Containers (production)**

- `web`: SvelteKit (Node adapter)
- `api`: FastAPI with in-process modules
- `worker`: jobs, outbox delivery, scheduled tasks
- `postgres` (or a managed Postgres in a Swiss region), `valkey`
- `proxy`: Caddy/nginx with TLS for all tenant domains

**Delivery**

1. Git push to `main` runs CI: lint, type checks, unit tests, tenant-isolation tests, container scan.
2. Images are built, tagged with the commit SHA and pushed to a private registry.
3. Staging deploys automatically; production deploys on a tagged release.
4. Migrations run as a separate step before the new `api` starts; they must be backwards compatible for one release.

**Operations**

- Monitoring: uptime checks per tenant domain, error rate, latency, queue depth; alerts to Teams.
- Backups: nightly Postgres dumps + WAL archiving (point-in-time recovery), object storage versioning.
- Tenant onboarding: in the platform operator console, or via `heinzel tenant create` for automation. It sets up tenant, domain, first admin invitation and default roles.

## Scope and roadmap

v1 delivers the core platform only. All modules are out of scope for the start. Each module is specified in its own tab under Modules, in a fixed format, and is built once the core is stable.

Module specifications: Modules

**Phases**

1. **Foundation**: tenant model, local user management and login (password + TOTP), RBAC, admin console, audit log, shell with tenant branding and light/dark mode, inbox (Mein Eingang), module loader. *Gate: two demo tenants fully isolated in tests.*
2. **Work engine**: forms, workflow, orders, notifications, files, directory, read-only MCP tools. *Gate: a configured request type (e.g. Berechtigungsantrag) and a generic order type work end to end at Schmelzi.*
3. **Collections and AI**: collections as Excel replacement by configuration, global search, MCP write tools with confirmation. *Gate: first Excel tool retired without writing a module.*
4. **Integrations (out of current scope)**: Entra ID login with account linking and group mapping, Microsoft 365 mail and Teams, SharePoint, TOPSOZ; specified later.
5. **Modules**: first Aufgaben (simple to-do lists) as soon as the work engine stands, as the proof of the module contract; then one at a time from their tabs.
6. **Productisation**: tenant self-service onboarding, second tenant, admin docs. Later: installable web app (PWA), then desktop and mobile apps (see Clients).

## Brief for Claude Design

Draft 1 is on the canvas: [Heinzel: Core, Admin & Unterhalt (Draft 1)](https://claude.ai/artifact/PZTebzCJLQTwez8bjzeZCA). It covers the core, administration and Störungsmeldungen as an example module, in Stiftung Schmelzi branding, light and dark. The decisions made there are reflected throughout this document.

**UX principles**

- **Task first**: the home screen answers "what do I need to do" and "what can I do", not "which modules exist".
- **Plain, friendly language**: de-CH with "du" ("Grüezi, Silas", "Was möchtest du tun?"), no IT jargon, a verb on every action ("Störung melden", "Selbst übernehmen").
- **Tenant brand first**: tenant logo and colours lead; Heinzel shows only as "powered by".
- **Warm but professional**: warm off-white background, one primary and one accent colour from the tenant, soft status badges, Figtree, rounded corners (10 to 14 px), no gradients or decoration for its own sake.
- **Light and dark from the same tokens**: one set of screens, the mode is a user setting.
- **Three clicks to submit**: any common report or request can be started from home and submitted in three steps or fewer.
- **Mobile for the field**: forms in numbered steps, large choice buttons (e.g. urgency), photo from the camera, usable one-handed.
- **Status always visible**: every item shows where it is, who has it and what happens next.
- **Accessible**: real buttons, links and labels, 44 px touch targets, AA contrast in both modes.

**Screens for v1**

| # | Screen | Key content | Draft 1 |
| --- | --- | --- | --- |
| 1 | Login | Tenant logo and name, username and password, 2FA hint, "Passwort vergessen", light/dark switch, "powered by Heinzel" | Done |
| 2 | Übersicht | Greeting, quick actions and widgets from modules, "Wartet auf dich" (inbox summary), hint for planned modules | Done |
| 3 | App shell | Tenant logo (links to Übersicht), Übersicht, Mein Eingang, tenant areas with modules and sub-navigation, Administration, light/dark switch, profile (links to Mein Profil), "powered by" | Done |
| 4 | Mein Eingang | List with source, task or notice, unread dot; detail with routing reason, module actions and link into the module | Done |
| 5 | Mein Profil: Sprache & Region | Language, time zone, date format, 12/24 h, first day of week, number format; "Standard" option per setting; live preview | Done |
| 6 | Admin: Benutzer & Rollen | Invite users, user table with 2FA status, permission matrix grouped by core and module | Done |
| 7 | Admin: Module | Module list with area and status; detail with on/off, area, sub-navigation toggles, role mapping, settings, MCP tools | Done |
| 8 | Admin: Einstellungen, Sprache & Region | Available languages, defaults per setting, "Benutzer dürfen ändern" lock per setting, live preview | Done |
| 9 | Admin: Einstellungen, Branding, Navigation, Anmeldung, E-Mail | Branding (name, logos light/dark/mark, primary and accent, WCAG contrast check, light and dark preview, default theme, "powered by"); Navigation (areas, order, hide empty areas, sidebar preview); Anmeldung (local accounts, 2FA policy, password length, self-service reset, lockout, session timeout, external providers as planned); E-Mail (sender, SMTP with test mail, templates) | Done |
| 10 | Audit-Log | Integrity banner (hash chain), filters, channel badges Web/API/MCP, before/after diff, export | Done |
| 11 | Admin: KI / MCP | Connected AI clients, enabled tools, active tokens, revoke | Open |
| 12 | Plattform-Betrieb | Tenants, domains, first admin invitation, health | Open |
| 13 | Example module: Störungsmeldungen Board | Sub-navigation Board, Liste, Meine Meldungen; cards with location, urgency, assignee | Done |
| 14 | Example module: Störung melden (mobile) | Four numbered steps, urgency as large buttons, emergency hint | Done |
| 15 | Suche (Dialog) | Opens from the sidebar (Ctrl K); results grouped by module data with counts, filter chips, highlighted matches, keyboard hints, note that only permitted results show | Done |
| 16 | Module Aufgaben: Meine Aufgaben | Quick-add, one list sorted by due date with due tag, show/hide done, tick off, detail panel; home widget "Heute fällig", quick action, inbox item for assigned tasks | Done |
| 17 | Admin: Module › Aufgaben | On/off, role mapping, position in the sidebar (top section), no sub-items, module settings, home and search toggles, MCP tools | Done |

**Next steps for Claude Design**

1. Extract the look into a Design System (tokens for light and dark, components), so a tenant only swaps primary, accent and logos.
2. Design the open screens: Mandant & Branding, KI / MCP, Plattform-Betrieb.
3. Add a fictional second tenant theme to prove branding is configuration only.
4. Empty and error states: no modules active, empty inbox, failed login, missing permission.

## Open decisions

- [ ] Hosting provider in Switzerland (VMs + managed Postgres + S3) and who operates it: you, CFU, or another partner
- [ ] Is client data (Bewohnende, health, social) in scope for v1? Drives DSFA and sensitive-field handling
- [ ] Which Excel tools migrate first? List them with owner and usage frequency
- [ ] Entra ID as login provider: which phase, and who at Schmelzi or the IT provider can grant admin consent for the app registration
- [ ] Integrations (later): which systems and in which order, e.g. Entra ID, Microsoft 365, SharePoint, TOPSOZ, Mitel, calendar
- [ ] Product licensing if other organisations use Heinzel: open source, SaaS fee, or source-available
- [ ] Name check: Swissreg trademark search and domain availability for "Heinzel"
- [ ] LLM provider and data location for in-app AI features (later phase)
