# Module template

Every module tab uses exactly these sections, in this order. A module is one feature, not a department; departments are navigation areas that group modules. The sections map one to one onto the module manifest (`heinzel.module.yaml`), so a finished tab is enough input for Claude Design (section 7) and Claude Code (all sections). Write "To be defined" rather than leaving a section out.

| Field | Value |
| --- | --- |
| Module ID | Lowercase key used in code and permissions, e.g. `unterhalt` |
| Area | Default navigation area, e.g. Unterhalt (the tenant admin can move it) |
| Status | Out of scope (v1) · Specified · In progress · Live |
| Business owner | Person who decides on scope and accepts the module |
| Runtime | In-process · Configuration only (no code, built from collections, request and order types) |
| Replaces | Excel tool, paper form or process it replaces |

## 1. Purpose

One or two sentences: which problem it solves and for whom.

## 2. Users and roles

| Role | What they do in this module |
| --- | --- |
|  |  |

## 3. Use cases

Numbered user stories: "As \<role>, I want \<action>, so that \<outcome>." Mark the ones needed for the first release.

## 4. Data

Entities with key fields, which fields are sensitive (personal, health, financial), and the retention period.

## 5. Core services used

Which of: identity, permissions, forms, workflow, orders, notifications, audit, files, directory, collections, search.

## 6. Permissions

| Permission | Description | Default roles |
| --- | --- | --- |
| `<module>.<object>.<action>` |  |  |

## 7. UI and contributions

Screens, navigation entry with its sub-navigation (children), dashboard widgets, request types, order types, collections, workflows, notification templates, scheduled jobs.

## 8. MCP surface

| Tool / resource / prompt | Permission | Read or write |
| --- | --- | --- |
|  |  |  |

Or `mcp: excluded` with the reason.

## 9. Events

Events published and subscribed. Integrations with external systems are listed here only as later candidates.

## 10. Migration

Existing data (Excel, paper, other tools), how it is imported, and the cut-over.

## 11. Open questions

- [ ]
