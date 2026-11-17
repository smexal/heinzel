# Aufgaben

| Field | Value |
| --- | --- |
| Module ID | `aufgaben` |
| Area | Top section, below Übersicht and Mein Eingang (no area) |
| Status | Specified, first module |
| Business owner | Leitung IT |
| Runtime | In-process |
| Replaces | Personal notes, sticky notes and Excel to-do lists |

## 1. Purpose

Simple to-do lists for individuals and small teams: capture a task in one line, give it a due date, assign it, tick it off. Deliberately small: no projects, no dependencies, no time tracking.

## 2. Users and roles

| Role | What they do in this module |
| --- | --- |
| Staff | Own personal list; create and complete tasks; take part in shared lists |
| List owner | Creates a shared list, adds and removes members |
| List member | Sees all tasks of the list, creates, assigns and completes them |

Access to a shared list comes from membership, not from a role.

## 3. Use cases

1. As staff, I want to add a task in one line with an optional due date, so capturing takes seconds. (v1)
2. As staff, I want to tick a task off and hide or show done tasks with one switch, so my list stays clean. (v1)
3. As staff, I want one list sorted by due date, without grouping; the due date is a tag, with overdue and today highlighted. (v1)
4. As list owner, I want a shared list (e.g. Sekretariat, IT-Team) with members. (v1)
5. As list member, I want to assign a task to another member, who then gets it in Mein Eingang. (v1)
6. As staff, I want to see what is due today on the Übersicht. (v1)
7. As staff, I want to ask an AI client "what is due today?" or "add task X". (v1)
8. As staff, I want to add pictures to a task (on the phone directly from the camera), so others see what is meant. (v1) Later: recurring tasks, checklists inside a task, other file types.

## 4. Data

| Entity | Key fields |
| --- | --- |
| `task_list` | name, kind (personal or shared), owner\_id |
| `task_list_member` | list\_id, user\_id, role (owner or member) |
| `task` | list\_id, title, note, due\_date, assignee\_id, status (open or done), done\_at, done\_by, position, created\_by |

No sensitive fields by design; notes can contain personal information, so a task is only visible to members of its list. Retention: done tasks are deleted after the period set in the module settings (default 24 months), together with their images. Images are core attachments (files service, per-tenant storage, virus scan) linked to the task and visible only to members of the task's list.

## 5. Core services used

Identity, permissions, inbox, notifications, audit, directory (members), search, files (task images). Own tables instead of the work items engine, to stay simple.

## 6. Permissions

| Permission | Description | Default roles |
| --- | --- | --- |
| `aufgaben.use` | Use the module: personal list, tasks in lists you belong to | Staff |
| `aufgaben.list.share` | Create shared lists and invite members | Staff |

## 7. UI and contributions

Navigation: a single entry "Aufgaben" in the top section below Mein Eingang, without sub-navigation; switching lists happens on the page. Screen: one list with quick-add field, sorted by due date, due date as a tag, switch "Erledigte anzeigen", picture count in the task line, image gallery and "Bild hinzufügen" (camera on phones) in the detail panel, checkbox per task, detail panel (due date, assignee, creator, note). Quick action "Aufgabe erfassen" and home widget "Heute fällig". Inbox: task "Zugewiesen: …" with actions Erledigt and Öffnen; notice to the creator when an assigned task is done. Search provider: tasks by title and note.

Module settings (`settings_schema`, edited under Administration › Module › Aufgaben):

| Setting | Options | Default |
| --- | --- | --- |
| Zuweisen an | Only list members · all users of the tenant | Only list members |
| Erinnerung bei Fälligkeit | Inbox on due date · inbox and email · none | Inbox on due date |
| Erledigte Aufgaben löschen | after 6, 12 or 24 months · never | after 24 months |
| Name der persönlichen Liste | Text | Meine Aufgaben |
| Geteilte Listen erlauben | On · off | On |
| Schnellaktion, Widget "Heute fällig", Suche | On · off each | On |
| Wiederkehrende Aufgaben | Later | Off |

## 8. MCP surface

| Tool / resource / prompt | Permission | Read or write |
| --- | --- | --- |
| `aufgaben.task.list` (filter: list, due, assignee) | `aufgaben.use` | Read |
| `aufgaben.task.create` | `aufgaben.use` | Write |
| `aufgaben.task.complete` | `aufgaben.use` | Write, idempotent |
| Resource `heinzel://aufgaben/lists/{id}` | `aufgaben.use` | Read |
| Prompt `heute-faellig` | `aufgaben.use` | Read |

## 9. Events

Publishes `aufgaben.task.assigned` and `aufgaben.task.completed`. Subscribes to `core.user.deactivated` to hand open tasks back to the list owner.

## 10. Migration

None required. Optional CSV import of existing to-do lists later.

## 11. Open questions

- [ ] Decided: Aufgaben sits in the top section below Mein Eingang, without sub-navigation.
- [ ] Should members see done tasks of a shared list forever or only for 30 days?
- [ ] Decided: the reminder channel is a module setting (inbox, inbox and email, none).
- [ ] Recurring tasks already in v1?
