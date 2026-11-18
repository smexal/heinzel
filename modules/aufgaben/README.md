# Modul: Aufgaben

Simple to-do lists for individuals and small teams. First module, built as the proof of the module contract.

- Spec: [`docs/concept/modules/aufgaben.md`](../../docs/concept/modules/aufgaben.md)
- Manifest: [`heinzel.module.yaml`](heinzel.module.yaml)
- Settings: [`settings.schema.json`](settings.schema.json)

Status: v1 implemented (everything in the spec except the MCP tools, which come with the MCP gateway).

| Part | Where |
| --- | --- |
| Backend package (loaded by the core as `heinzel_modules.aufgaben`) | `backend/__init__.py` (`setup`: router, search provider, file access, inbox action, event handler, widget, jobs) |
| Rules (shared by routes, inbox action, jobs, later MCP) | `backend/service.py` |
| API under `/api/v1/aufgaben` | `backend/routes.py` |
| Tables in schema `mod_aufgaben` | `backend/models.py`, migrations in `backend/migrations/` |
| UI | `apps/web/src/routes/(app)/aufgaben/` |
| Tests | `apps/api/tests/test_aufgaben.py` |

Behaviour worth knowing:
- Every user gets a personal list on first use; its name comes from the module setting.
- A task is visible to the members of its list and to its assignee. Only members delete or move it.
- A task has a checklist (points with text, done, position) and attachments: pictures and common
  documents (PDF, Office, OpenDocument, TXT/CSV) through the core files service.
- Assigning someone puts "Zugewiesen: …" with the action "Erledigt" into their Mein Eingang;
  reassigning moves it, completing closes it and sends the creator a notice.
- Reminders (job every 15 min): one per due date, to the assignee or else the creator; e-mail too
  when the setting says so. Retention (job every 6 h) deletes done tasks with their pictures.
- A deactivated user's open tasks go back to the list owner.
