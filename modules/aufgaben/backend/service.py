"""Aufgaben: the rules, shared by the web routes, inbox actions, jobs and (later) MCP tools.

Visibility: a task is visible to the members of its list and to its assignee. Members may do
everything with the list's tasks; an assignee who is not a member may edit, complete and add
pictures, but not delete or move the task. Every write is audited and keeps the search index
and Mein Eingang current in the same transaction.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from heinzel_api import audit, events, files, inbox, localization, search
from heinzel_api.models import User
from heinzel_api.tenants import TenantConfig
from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.orm import Session

from .models import Task, TaskList, TaskListMember

MODULE = "aufgaben"
USE = "aufgaben.use"
SHARE = "aufgaben.list.share"

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


class Forbidden(Exception):
    pass


class NotFound(Exception):
    pass


class Invalid(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Actor:
    """Who acts, with the module settings of the tenant and their local 'today'."""

    tenant_id: uuid.UUID
    tenant: TenantConfig
    user_id: uuid.UUID
    settings: dict
    today: date
    channel: str = "web"
    ip: str | None = None
    can_share: bool = False


def today_in(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def tenant_today(tenant: TenantConfig) -> date:
    return today_in(localization.defaults(tenant)["timezone"])


def due_label(d: date | None, today: date) -> str:
    if d is None:
        return "Kein Datum"
    if d == today:
        return "Heute"
    if d == today + timedelta(days=1):
        return "Morgen"
    short = f"{WEEKDAYS[d.weekday()]}, {d.day:02d}.{d.month:02d}."
    if d.year != today.year:
        short = f"{short}{d.year}"
    return f"Überfällig · {short}" if d < today else short


def _plain_due(d: date, today: date) -> str:
    """'heute', 'Mo, 16.11.' (without the overdue prefix), for context lines."""
    label = due_label(d, today).replace("Überfällig · ", "")
    return label.lower() if label in ("Heute", "Morgen") else label


# --- lists -----------------------------------------------------------------------------------


def list_name(lst: TaskList, settings: dict) -> str:
    return lst.name if lst.kind == "shared" and lst.name else settings["personal_list_name"]


def personal_list(s: Session, actor: Actor) -> TaskList:
    lst = s.scalar(
        select(TaskList).where(TaskList.kind == "personal", TaskList.owner_id == actor.user_id)
    )
    if lst is None:
        lst = TaskList(tenant_id=actor.tenant_id, kind="personal", owner_id=actor.user_id)
        s.add(lst)
        s.flush()
        s.add(
            TaskListMember(
                list_id=lst.id, user_id=actor.user_id, tenant_id=actor.tenant_id, role="owner"
            )
        )
        s.flush()
    return lst


def member_role(s: Session, list_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    return s.scalar(
        select(TaskListMember.role).where(
            TaskListMember.list_id == list_id, TaskListMember.user_id == user_id
        )
    )


def my_lists(s: Session, actor: Actor) -> list[tuple[TaskList, str]]:
    """Lists the user belongs to: personal first, then shared by name."""
    personal_list(s, actor)
    rows = s.execute(
        select(TaskList, TaskListMember.role)
        .join(TaskListMember, TaskListMember.list_id == TaskList.id)
        .where(TaskListMember.user_id == actor.user_id)
    ).all()
    return sorted(
        [(lst, role) for lst, role in rows],
        key=lambda r: (r[0].kind != "personal", (r[0].name or "").lower()),
    )


def get_list(s: Session, actor: Actor, list_id: uuid.UUID, owner: bool = False) -> TaskList:
    lst = s.get(TaskList, list_id)
    role = member_role(s, list_id, actor.user_id) if lst else None
    if lst is None or role is None:
        raise NotFound()
    if owner and role != "owner":
        raise Forbidden()
    return lst


def _require_sharing(actor: Actor) -> None:
    if not actor.settings.get("shared_lists_enabled", True):
        raise Invalid("shared_lists_disabled")
    if not actor.can_share:
        raise Forbidden()


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise Invalid("name_required")
    return name[:80]


def create_list(s: Session, actor: Actor, name: str) -> TaskList:
    _require_sharing(actor)
    lst = TaskList(
        tenant_id=actor.tenant_id, kind="shared", name=_clean_name(name), owner_id=actor.user_id
    )
    s.add(lst)
    s.flush()
    s.add(
        TaskListMember(
            list_id=lst.id, user_id=actor.user_id, tenant_id=actor.tenant_id, role="owner"
        )
    )
    _audit(s, actor, "aufgaben.list.created", "task_list", lst.id, {"name": lst.name})
    return lst


def rename_list(s: Session, actor: Actor, list_id: uuid.UUID, name: str) -> TaskList:
    lst = get_list(s, actor, list_id, owner=True)
    if lst.kind != "shared":
        raise Invalid("personal_list")
    old, lst.name = lst.name, _clean_name(name)
    _audit(s, actor, "aufgaben.list.renamed", "task_list", lst.id, {"from": old, "to": lst.name})
    for task in s.scalars(select(Task).where(Task.list_id == lst.id)):
        index_task(s, actor, task, lst)
    return lst


def delete_list(s: Session, actor: Actor, list_id: uuid.UUID, storage) -> int:
    lst = get_list(s, actor, list_id, owner=True)
    if lst.kind != "shared":
        raise Invalid("personal_list")
    tasks = list(s.scalars(select(Task).where(Task.list_id == lst.id)))
    for task in tasks:
        _forget_task(s, actor, task, storage)
    _audit(
        s,
        actor,
        "aufgaben.list.deleted",
        "task_list",
        lst.id,
        {"name": lst.name, "tasks": len(tasks)},
    )
    s.delete(lst)
    s.flush()
    return len(tasks)


def members(s: Session, list_id: uuid.UUID) -> list[tuple[User, str]]:
    return list(
        s.execute(
            select(User, TaskListMember.role)
            .join(TaskListMember, TaskListMember.user_id == User.id)
            .where(TaskListMember.list_id == list_id)
            .order_by(TaskListMember.role.desc(), User.display_name)
        ).all()
    )


def _active_user(s: Session, user_id: uuid.UUID) -> User:
    user = s.get(User, user_id)
    if user is None or user.status == "deactivated":
        raise Invalid("unknown_user")
    return user


def add_member(s: Session, actor: Actor, list_id: uuid.UUID, user_id: uuid.UUID) -> None:
    lst = get_list(s, actor, list_id, owner=True)
    if lst.kind != "shared":
        raise Invalid("personal_list")
    user = _active_user(s, user_id)
    if member_role(s, lst.id, user.id) is None:
        s.add(TaskListMember(list_id=lst.id, user_id=user.id, tenant_id=actor.tenant_id))
        s.flush()
        _audit(s, actor, "aufgaben.list.member_added", "task_list", lst.id, {"user": str(user.id)})
        inbox.deliver(
            s,
            actor.tenant_id,
            [user.id],
            source=MODULE,
            kind="notice",
            title=f"Neue geteilte Liste: {lst.name}",
            reason="Du wurdest als Mitglied hinzugefügt.",
            link=f"/aufgaben?liste={lst.id}",
            actor_user_id=actor.user_id,
        )


def remove_member(s: Session, actor: Actor, list_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """The owner removes a member, or a member leaves. The owner cannot leave."""
    lst = get_list(s, actor, list_id, owner=user_id != actor.user_id)
    role = member_role(s, lst.id, user_id)
    if role is None:
        raise NotFound()
    if role == "owner":
        raise Invalid("owner_stays")
    s.execute(
        delete(TaskListMember).where(
            TaskListMember.list_id == lst.id, TaskListMember.user_id == user_id
        )
    )
    # Their open tasks in this list go back to nobody; the list sees them unassigned.
    for task in s.scalars(
        select(Task).where(
            Task.list_id == lst.id, Task.assignee_id == user_id, Task.status == "open"
        )
    ):
        _assign(s, actor, task, lst, None)
    _audit(s, actor, "aufgaben.list.member_removed", "task_list", lst.id, {"user": str(user_id)})


# --- tasks -----------------------------------------------------------------------------------


def visible_filter(user_id: uuid.UUID):
    member = exists().where(
        TaskListMember.list_id == Task.list_id, TaskListMember.user_id == user_id
    )
    return or_(member, Task.assignee_id == user_id)


def get_task(s: Session, actor: Actor, task_id: uuid.UUID) -> tuple[Task, TaskList, bool]:
    """(task, its list, actor is member). NotFound when the actor may not see it."""
    task = s.get(Task, task_id)
    if task is None:
        raise NotFound()
    is_member = member_role(s, task.list_id, actor.user_id) is not None
    if not is_member and task.assignee_id != actor.user_id:
        raise NotFound()
    return task, s.get(TaskList, task.list_id), is_member


def tasks(
    s: Session, actor: Actor, list_id: uuid.UUID | None = None, include_done: bool = False
) -> list[Task]:
    """Sorted by due date (no date last), then by creation. list_id None: all my lists and
    everything assigned to me."""
    q = select(Task).where(visible_filter(actor.user_id))
    if list_id is not None:
        get_list(s, actor, list_id)
        q = q.where(Task.list_id == list_id)
    if not include_done:
        q = q.where(Task.status == "open")
    q = q.order_by(
        (Task.status == "done").asc(),
        Task.due_date.asc().nulls_last(),
        Task.position,
        Task.created_at,
    )
    return list(s.scalars(q))


def counts(s: Session, actor: Actor, list_id: uuid.UUID | None = None) -> tuple[int, int]:
    q = select(Task.status, func.count()).where(visible_filter(actor.user_id))
    if list_id is not None:
        q = q.where(Task.list_id == list_id)
    by = dict(s.execute(q.group_by(Task.status)).all())
    return by.get("open", 0), by.get("done", 0)


def _check_assignee(s: Session, actor: Actor, lst: TaskList, user_id: uuid.UUID | None) -> None:
    if user_id is None:
        return
    _active_user(s, user_id)
    members_only = actor.settings.get("assign_scope", "list_members") == "list_members"
    if members_only and member_role(s, lst.id, user_id) is None:
        raise Invalid("assignee_not_member")


def create_task(
    s: Session,
    actor: Actor,
    *,
    title: str,
    list_id: uuid.UUID | None = None,
    due_date: date | None = None,
    assignee_id: uuid.UUID | None = None,
    note: str = "",
) -> Task:
    title = " ".join(title.split())
    if not title:
        raise Invalid("title_required")
    lst = get_list(s, actor, list_id) if list_id else personal_list(s, actor)
    _check_assignee(s, actor, lst, assignee_id)
    task = Task(
        tenant_id=actor.tenant_id,
        list_id=lst.id,
        title=title[:300],
        note=note,
        due_date=due_date,
        created_by=actor.user_id,
    )
    s.add(task)
    s.flush()
    _audit(s, actor, "aufgaben.task.created", "task", task.id, {"title": task.title})
    if assignee_id is not None:
        _assign(s, actor, task, lst, assignee_id)
    index_task(s, actor, task, lst)
    return task


def update_task(
    s: Session, actor: Actor, task_id: uuid.UUID, changes: dict
) -> tuple[Task, TaskList]:
    """changes: any of title, note, due_date, assignee_id, list_id (only set keys change)."""
    task, lst, is_member = get_task(s, actor, task_id)
    before = {}
    if "list_id" in changes and changes["list_id"] != task.list_id:
        if not is_member:
            raise Forbidden()
        lst = get_list(s, actor, changes["list_id"])
        if (
            task.assignee_id
            and actor.settings.get("assign_scope") != "tenant"
            and member_role(s, lst.id, task.assignee_id) is None
        ):
            _assign(s, actor, task, lst, None)
        before["list_id"] = str(task.list_id)
        task.list_id = lst.id
    if "title" in changes:
        title = " ".join((changes["title"] or "").split())
        if not title:
            raise Invalid("title_required")
        before["title"], task.title = task.title, title[:300]
    if "note" in changes:
        before["note"] = "…"
        task.note = changes["note"] or ""
    if "due_date" in changes and changes["due_date"] != task.due_date:
        before["due_date"] = task.due_date.isoformat() if task.due_date else None
        task.due_date = changes["due_date"]
        task.reminded_on = None
    if "assignee_id" in changes and changes["assignee_id"] != task.assignee_id:
        _check_assignee(s, actor, lst, changes["assignee_id"])
        _assign(s, actor, task, lst, changes["assignee_id"])
    if before:
        task.updated_at = datetime.now(UTC)
        _audit(s, actor, "aufgaben.task.updated", "task", task.id, {"changed": sorted(before)})
    if task.assignee_id and task.status == "open" and task.assignee_id != actor.user_id:
        _deliver_assignment(s, actor, task, lst, renew=False)
    index_task(s, actor, task, lst)
    s.flush()
    return task, lst


def _assign(s: Session, actor: Actor, task: Task, lst: TaskList, user_id: uuid.UUID | None) -> None:
    previous = task.assignee_id
    task.assignee_id = user_id
    inbox.resolve(s, source=MODULE, ref_type="task", ref_id=str(task.id), kind="task")
    _audit(
        s,
        actor,
        "aufgaben.task.assigned",
        "task",
        task.id,
        {"from": str(previous) if previous else None, "to": str(user_id) if user_id else None},
    )
    if user_id is not None and user_id != actor.user_id and task.status == "open":
        _deliver_assignment(s, actor, task, lst, renew=True)
        events.publish(
            s, actor.tenant_id, "aufgaben.task.assigned", task_id=task.id, assignee_id=user_id
        )


def _deliver_assignment(s: Session, actor: Actor, task: Task, lst: TaskList, renew: bool) -> None:
    """The assignee's inbox item. renew=False only refreshes an item that is still open."""
    if not renew and not s.scalar(
        select(func.count())
        .select_from(inbox.InboxItem)
        .where(
            inbox.InboxItem.source == MODULE,
            inbox.InboxItem.ref_type == "task",
            inbox.InboxItem.ref_id == str(task.id),
            inbox.InboxItem.done_at.is_(None),
        )
    ):
        return
    name = list_name(lst, actor.settings)
    due = due_label(task.due_date, actor.today)
    imgs = [
        a.id
        for a in files.for_target(s, module=MODULE, target_type="task", target_id=str(task.id))
        if a.content_type in files.IMAGE_TYPES
    ]
    creator = s.get(User, task.created_by) if task.created_by else None
    inbox.deliver(
        s,
        actor.tenant_id,
        [task.assignee_id],
        source=MODULE,
        kind="task",
        title=f"Zugewiesen: {task.title}",
        context=f"{name} · fällig {due.lower()}" if task.due_date else name,
        body=task.note or None,
        reason="Die Aufgabe wurde dir zugewiesen.",
        facts=[("Liste", name), ("Fällig", due)]
        + ([("Erstellt von", creator.display_name)] if creator else []),
        link=f"/aufgaben?aufgabe={task.id}",
        actions=[inbox.Action("done", "Erledigt", "primary")],
        attachments=imgs,
        ref_type="task",
        ref_id=str(task.id),
        actor_user_id=actor.user_id,
        due_at=datetime.combine(task.due_date, datetime.min.time(), UTC) if task.due_date else None,
    )


def complete(s: Session, actor: Actor, task_id: uuid.UUID) -> Task:
    """Idempotent: completing a done task changes nothing."""
    task, lst, _ = get_task(s, actor, task_id)
    if task.status == "done":
        return task
    task.status, task.done_at, task.done_by = "done", datetime.now(UTC), actor.user_id
    inbox.resolve(s, source=MODULE, ref_type="task", ref_id=str(task.id))
    _audit(s, actor, "aufgaben.task.completed", "task", task.id, {"title": task.title})
    if task.assignee_id and task.created_by and actor.user_id != task.created_by:
        done_by = s.get(User, actor.user_id)
        inbox.deliver(
            s,
            actor.tenant_id,
            [task.created_by],
            source=MODULE,
            kind="notice",
            title=f"Erledigt: {task.title}",
            context=f"{list_name(lst, actor.settings)} · von {done_by.display_name}",
            reason="Du hast die Aufgabe erstellt.",
            link=f"/aufgaben?aufgabe={task.id}",
            ref_type="task-done",
            ref_id=str(task.id),
            actor_user_id=actor.user_id,
        )
    events.publish(s, actor.tenant_id, "aufgaben.task.completed", task_id=task.id)
    index_task(s, actor, task, lst)
    s.flush()
    return task


def reopen(s: Session, actor: Actor, task_id: uuid.UUID) -> Task:
    task, lst, _ = get_task(s, actor, task_id)
    if task.status == "open":
        return task
    task.status, task.done_at, task.done_by = "open", None, None
    inbox.resolve(s, source=MODULE, ref_type="task-done", ref_id=str(task.id))
    _audit(s, actor, "aufgaben.task.reopened", "task", task.id, {"title": task.title})
    if task.assignee_id and task.assignee_id != actor.user_id:
        _deliver_assignment(s, actor, task, lst, renew=True)
    index_task(s, actor, task, lst)
    s.flush()
    return task


def delete_task(s: Session, actor: Actor, task_id: uuid.UUID, storage) -> None:
    task, _lst, is_member = get_task(s, actor, task_id)
    if not is_member:
        raise Forbidden()
    _forget_task(s, actor, task, storage)
    _audit(s, actor, "aufgaben.task.deleted", "task", task.id, {"title": task.title})
    s.delete(task)
    s.flush()


def _forget_task(s: Session, actor: Actor, task: Task, storage) -> None:
    files.delete_for_target(s, storage, module=MODULE, target_type="task", target_id=str(task.id))
    inbox.resolve(s, source=MODULE, ref_type="task", ref_id=str(task.id))
    inbox.resolve(s, source=MODULE, ref_type="task-done", ref_id=str(task.id))
    search.remove(s, actor.tenant_id, module=MODULE, entity_type="task", entity_id=str(task.id))


# --- pictures --------------------------------------------------------------------------------


def images(s: Session, task: Task) -> list:
    return files.for_target(s, module=MODULE, target_type="task", target_id=str(task.id))


def add_images(s: Session, actor: Actor, task_id: uuid.UUID, ids: list[uuid.UUID]) -> list:
    task, _lst, _ = get_task(s, actor, task_id)
    try:
        atts = files.link(
            s,
            ids,
            module=MODULE,
            target_type="task",
            target_id=str(task.id),
            user_id=actor.user_id,
        )
    except files.UploadRejected as e:
        raise Invalid(e.code) from e
    if any(a.content_type not in files.IMAGE_TYPES for a in atts):
        raise Invalid("images_only")
    _audit(
        s, actor, "aufgaben.task.images_added", "task", task.id, {"files": [str(i) for i in ids]}
    )
    return atts


def remove_image(s: Session, actor: Actor, task_id: uuid.UUID, att_id: uuid.UUID, storage) -> None:
    task, _lst, _ = get_task(s, actor, task_id)
    att = next((a for a in images(s, task) if a.id == att_id), None)
    if att is None:
        raise NotFound()
    files.delete(s, storage, att)
    _audit(s, actor, "aufgaben.task.image_removed", "task", task.id, {"file": str(att_id)})


def image_counts(s: Session, task_ids: list[uuid.UUID]) -> dict[str, int]:
    if not task_ids:
        return {}
    rows = s.execute(
        select(files.Attachment.target_id, func.count())
        .where(
            files.Attachment.module == MODULE,
            files.Attachment.target_type == "task",
            files.Attachment.target_id.in_([str(i) for i in task_ids]),
            files.Attachment.deleted_at.is_(None),
        )
        .group_by(files.Attachment.target_id)
    ).all()
    return dict(rows)


# --- search, file access, inbox actions, events ----------------------------------------------


def index_task(s: Session, actor: Actor, task: Task, lst: TaskList) -> None:
    name = list_name(lst, actor.settings)
    meta = name
    if task.status == "done":
        chip = {"label": "Erledigt", "tone": "neutral"}
    elif task.due_date and task.due_date < actor.today:
        chip = {"label": "Überfällig", "tone": "red"}
    elif task.due_date == actor.today:
        chip = {"label": "Heute", "tone": "amber"}
    else:
        chip = None
    if task.due_date:
        meta += f" · fällig {due_label(task.due_date, actor.today).replace('Überfällig · ', '')}"
    search.index(
        s,
        actor.tenant_id,
        module=MODULE,
        entity_type="task",
        entity_id=str(task.id),
        title=task.title,
        body=task.note,
        meta=meta,
        link=f"/aufgaben?aufgabe={task.id}",
        permission=USE,
        chip=chip,
    )


def can_view_ids(s: Session, user_id: uuid.UUID, ids: list[str]) -> set[str]:
    uuids = []
    for i in ids:
        try:
            uuids.append(uuid.UUID(i))
        except ValueError:
            continue
    if not uuids:
        return set()
    rows = s.scalars(select(Task.id).where(Task.id.in_(uuids), visible_filter(user_id)))
    return {str(r) for r in rows}


def can_view_file(s: Session, user_id: uuid.UUID, target_id: str) -> bool:
    return bool(can_view_ids(s, user_id, [target_id]))


def _audit(
    s: Session, actor: Actor, action: str, target_type: str, target_id, data: dict | None = None
) -> None:
    audit.record(
        s,
        actor.tenant_id,
        action,
        actor_user_id=actor.user_id,
        channel=actor.channel,
        target_type=target_type,
        target_id=str(target_id),
        data=data,
        ip=actor.ip,
    )


def on_user_deactivated(s: Session, tenant_id: uuid.UUID, payload: dict) -> None:
    """Open tasks of a deactivated user go back to the list owner (shared lists) or to
    nobody."""
    user_id = payload["user_id"]
    rows = s.execute(
        select(Task, TaskList)
        .join(TaskList, TaskList.id == Task.list_id)
        .where(Task.assignee_id == user_id, Task.status == "open")
    ).all()
    for task, lst in rows:
        owner = lst.owner_id if lst.kind == "shared" and lst.owner_id != user_id else None
        task.assignee_id = owner
        inbox.resolve(s, source=MODULE, ref_type="task", ref_id=str(task.id), kind="task")
        audit.record(
            s,
            tenant_id,
            "aufgaben.task.assigned",
            actor_user_id=payload.get("actor_user_id"),
            channel="system",
            target_type="task",
            target_id=str(task.id),
            data={
                "from": str(user_id),
                "to": str(owner) if owner else None,
                "reason": "deactivated",
            },
        )
        if owner:
            inbox.deliver(
                s,
                tenant_id,
                [owner],
                source=MODULE,
                kind="task",
                title=f"Zurück bei dir: {task.title}",
                context=lst.name,
                reason=(
                    "Die zuständige Person wurde deaktiviert. "
                    "Die Aufgabe liegt jetzt bei dir als Besitzer der Liste."
                ),
                link=f"/aufgaben?aufgabe={task.id}",
                actions=[inbox.Action("done", "Erledigt", "primary")],
                ref_type="task",
                ref_id=str(task.id),
            )


# --- jobs ------------------------------------------------------------------------------------


def due_reminders(s: Session, tenant_id: uuid.UUID, tenant: TenantConfig, settings: dict) -> list:
    """Open tasks due today (or overdue and never reminded) get one inbox reminder for the
    assignee, or for the creator when nobody is assigned. Returns (task, user) for e-mail."""
    if settings.get("reminder", "inbox") == "none":
        return []
    today = tenant_today(tenant)
    rows = s.execute(
        select(Task, TaskList)
        .join(TaskList, TaskList.id == Task.list_id)
        .where(
            Task.status == "open",
            Task.due_date.is_not(None),
            Task.due_date <= today,
            or_(Task.reminded_on.is_(None), Task.reminded_on < Task.due_date),
        )
    ).all()
    sent = []
    for task, lst in rows:
        user_id = task.assignee_id or task.created_by
        if user_id is None:
            continue
        task.reminded_on = today
        name = list_name(lst, settings)
        inbox.deliver(
            s,
            tenant_id,
            [user_id],
            source=MODULE,
            kind="task",
            title=f"Heute fällig: {task.title}"
            if task.due_date == today
            else f"Überfällig: {task.title}",
            context=f"{name} · fällig {_plain_due(task.due_date, today)}",
            body=task.note or None,
            reason="Erinnerung bei Fälligkeit.",
            link=f"/aufgaben?aufgabe={task.id}",
            actions=[inbox.Action("done", "Erledigt", "primary")],
            ref_type="task",
            ref_id=str(task.id),
            due_at=datetime.combine(task.due_date, datetime.min.time(), UTC),
        )
        sent.append((task, user_id))
    return sent


def purge_done(s: Session, tenant_id: uuid.UUID, settings: dict, storage, now: datetime) -> int:
    """Delete done tasks older than the retention setting, with their pictures."""
    months = settings.get("delete_done_after_months", 24)
    if months is None:
        return 0
    cutoff = now - timedelta(days=round(months * 30.44))
    old = list(s.scalars(select(Task).where(and_(Task.status == "done", Task.done_at < cutoff))))
    for task in old:
        files.delete_for_target(
            s, storage, module=MODULE, target_type="task", target_id=str(task.id)
        )
        search.remove(s, tenant_id, module=MODULE, entity_type="task", entity_id=str(task.id))
        s.delete(task)
    if old:
        audit.record(
            s,
            tenant_id,
            "aufgaben.task.purged",
            channel="system",
            data={"count": len(old), "older_than_months": months},
        )
    s.flush()
    return len(old)
