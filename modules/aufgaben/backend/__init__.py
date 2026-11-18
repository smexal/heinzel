"""Aufgaben module: simple to-do lists for individuals and small teams.

Spec: docs/concept/modules/aufgaben.md. Registered with the core in setup():
API router, search provider, file access for task attachments, inbox action "Erledigt",
handler for core.user.deactivated, home widget "Heute fällig", jobs for due-date
reminders and retention of done tasks.
"""

import logging
import uuid
from datetime import UTC, datetime

from heinzel_api import events, files, inbox, localization, mail, search
from heinzel_api.db import tenant_session
from heinzel_api.models import InboxItem, User
from heinzel_api.modules import (
    JobContext,
    ModuleHost,
    Widget,
    WidgetContext,
    WidgetItem,
    is_enabled,
    settings_for,
)
from heinzel_api.tenants import config_in_session
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import service as svc
from .models import Task, TaskList, TaskListMember
from .routes import router

log = logging.getLogger(__name__)


def setup(host: ModuleHost) -> None:
    manifest = host.manifest
    host.add_router(router)
    search.register_provider(svc.MODULE, "task", can_view=svc.can_view_ids)
    files.register_access(svc.MODULE, "task", svc.can_view_file)
    events.subscribe("core.user.deactivated", svc.MODULE, svc.on_user_deactivated)

    def inbox_action(s: Session, item: InboxItem, key: str, user_id: uuid.UUID) -> str:
        if key != "done" or item.ref_type != "task" or not item.ref_id:
            raise ValueError("action_unavailable")
        tenant = config_in_session(s, item.tenant_id)
        if tenant is None or not is_enabled(tenant, svc.MODULE):
            raise ValueError("module_disabled")
        user = s.get(User, user_id)
        loc = localization.effective(tenant, user.preferences if user else {})
        actor = svc.Actor(
            tenant_id=item.tenant_id,
            tenant=tenant,
            user_id=user_id,
            settings=settings_for(tenant, manifest),
            today=svc.today_in(loc["timezone"]),
        )
        try:
            task = svc.complete(s, actor, uuid.UUID(item.ref_id))
        except svc.NotFound as e:
            raise PermissionError() from e
        return f"Erledigt: {task.title}"

    inbox.register_action(svc.MODULE, inbox_action)

    def due_today(ctx: WidgetContext) -> Widget | None:
        if svc.USE not in ctx.permissions:
            return None
        today = svc.today_in(ctx.localization["timezone"])
        s = ctx.session
        member = select(TaskListMember.list_id).where(TaskListMember.user_id == ctx.user_id)
        rows = s.execute(
            select(Task, TaskList)
            .join(TaskList, TaskList.id == Task.list_id)
            .where(
                Task.status == "open",
                Task.due_date <= today,
                or_(
                    Task.assignee_id == ctx.user_id,
                    Task.assignee_id.is_(None) & Task.list_id.in_(member),
                ),
            )
            .order_by(Task.due_date, Task.created_at)
            .limit(6)
        ).all()
        creators = {
            u.id: u.display_name
            for u in s.scalars(
                select(User).where(User.id.in_({t.created_by for t, _ in rows if t.created_by}))
            )
        }
        items = []
        for task, lst in rows:
            if task.due_date < today:
                meta, tone = svc.due_label(task.due_date, today).replace(" · ", " seit "), "danger"
            else:
                parts = [] if lst.kind == "personal" else [svc.list_name(lst, ctx.settings)]
                if task.created_by and task.created_by != ctx.user_id:
                    parts.append(f"von {creators.get(task.created_by, '')}")
                meta, tone = " · ".join(parts) or None, None
            items.append(
                WidgetItem(
                    title=task.title, meta=meta, tone=tone, href=f"/aufgaben?aufgabe={task.id}"
                )
            )
        return Widget(
            key="heute-faellig",
            module=svc.MODULE,
            eyebrow="Aufgaben",
            title="Heute fällig",
            link_label="Alle Aufgaben",
            link="/aufgaben",
            items=items,
            empty="Heute ist nichts fällig.",
        )

    host.add_widget("heute-faellig", due_today)

    def reminders(ctx: JobContext) -> None:
        for entry in ctx.tenants:
            if not is_enabled(entry.config, svc.MODULE):
                continue
            settings = settings_for(entry.config, manifest)
            outgoing: list[mail.Mail] = []
            with tenant_session(ctx.db, entry.id) as s:
                sent = svc.due_reminders(s, entry.id, entry.config, settings)
                if settings.get("reminder") == "inbox_and_email":
                    base = _base_url(entry.config, ctx.settings)
                    for task, user_id in sent:
                        user = s.get(User, user_id)
                        if user and user.status == "active":
                            outgoing.append(_reminder_mail(entry.config, user, task, base))
            for m in outgoing:
                ctx.mailer.send(entry.config, m)

    def retention(ctx: JobContext) -> None:
        for entry in ctx.tenants:
            if not is_enabled(entry.config, svc.MODULE):
                continue
            settings = settings_for(entry.config, manifest)
            with tenant_session(ctx.db, entry.id) as s:
                n = svc.purge_done(s, entry.id, settings, ctx.storage, datetime.now(UTC))
            if n:
                log.info("aufgaben: %s done tasks deleted for %s", n, entry.config.slug)

    host.add_job("reminders", 15 * 60, reminders)
    host.add_job("retention", 6 * 3600, retention)


def _base_url(tenant, settings) -> str:
    host = tenant.domains[0] if tenant.domains else "localhost"
    scheme = "https" if settings.secure_cookies else "http"
    return f"{scheme}://{host}"


def _reminder_mail(tenant, user: User, task: Task, base: str) -> mail.Mail:
    first = user.display_name.split(" ")[0]
    return mail.Mail(
        to=user.email,
        subject=f"Heute fällig: {task.title}",
        text=(
            f"Grüezi {first}\n\n"
            f"Diese Aufgabe ist fällig:\n{task.title}\n\n"
            f"Öffnen: {base}/aufgaben?aufgabe={task.id}\n\n"
            f"Die Erinnerung kommt von {tenant.display_name}. Die Einstellung legt die "
            "Administration unter Module › Aufgaben fest.\n"
        ),
    )
