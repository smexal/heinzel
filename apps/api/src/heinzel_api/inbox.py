"""Inbox (Mein Eingang): tasks and notices that modules and the core deliver to people.

Modules call deliver() inside the transaction of the change that causes it. With ref_type
and ref_id an item stands for one object: delivering again updates the open item (and marks
it unread) instead of adding another, and resolve() closes it for everyone once it is done.
Buttons on an item are actions the source handles (register_action).
"""

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from heinzel_api.models import InboxItem

CORE = "core"


@dataclass(frozen=True)
class Action:
    key: str
    label: str
    style: str = "secondary"  # primary | secondary | danger

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "label": self.label, "style": self.style}


def deliver(
    session: Session,
    tenant_id: uuid.UUID,
    user_ids: Iterable[uuid.UUID],
    *,
    source: str,
    kind: str,
    title: str,
    context: str | None = None,
    body: str | None = None,
    reason: str | None = None,
    facts: list[tuple[str, str]] | None = None,
    link: str | None = None,
    actions: list[Action] | None = None,
    attachments: list[uuid.UUID] | None = None,
    ref_type: str | None = None,
    ref_id: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    due_at: datetime | None = None,
    severity: str | None = None,
) -> list[InboxItem]:
    if kind not in ("task", "notice"):
        raise ValueError("kind must be 'task' or 'notice'")
    values: dict[str, Any] = {
        "severity": severity,
        "title": title[:300],
        "context": (context or None) and context[:300],
        "body": body,
        "reason": (reason or None) and reason[:300],
        "facts": [{"label": k, "value": v} for k, v in (facts or [])],
        "link": link,
        "actions": [a.as_dict() for a in (actions or [])],
        "attachments": list(attachments or []),
        "actor_user_id": actor_user_id,
        "due_at": due_at,
    }
    now = datetime.now(UTC)
    items = []
    for user_id in dict.fromkeys(user_ids):  # unique, order kept
        if actor_user_id is not None and user_id == actor_user_id and kind == "notice":
            continue  # nobody needs a notice about their own action
        existing = None
        if ref_type and ref_id:
            existing = session.scalar(
                select(InboxItem).where(
                    InboxItem.user_id == user_id,
                    InboxItem.source == source,
                    InboxItem.kind == kind,
                    InboxItem.ref_type == ref_type,
                    InboxItem.ref_id == ref_id,
                    InboxItem.done_at.is_(None),
                )
            )
        if existing is not None:
            for k, v in values.items():
                setattr(existing, k, v)
            existing.read_at = None
            existing.updated_at = now
            items.append(existing)
        else:
            item = InboxItem(
                tenant_id=tenant_id,
                user_id=user_id,
                source=source,
                kind=kind,
                ref_type=ref_type,
                ref_id=ref_id,
                **values,
            )
            session.add(item)
            items.append(item)
    session.flush()
    return items


def resolve(
    session: Session, *, source: str, ref_type: str, ref_id: str, kind: str | None = None
) -> int:
    """Close the open items for an object (e.g. the task was done by someone)."""
    stmt = (
        update(InboxItem)
        .where(
            InboxItem.source == source,
            InboxItem.ref_type == ref_type,
            InboxItem.ref_id == ref_id,
            InboxItem.done_at.is_(None),
        )
        .values(done_at=datetime.now(UTC))
    )
    if kind:
        stmt = stmt.where(InboxItem.kind == kind)
    return session.execute(stmt).rowcount or 0


# Actions: source -> handler(session, item, action_key, user_id) -> message for the user.
# The handler checks permissions itself and raises PermissionError or ValueError.
ActionHandler = Callable[[Session, InboxItem, str, uuid.UUID], str]
_handlers: dict[str, ActionHandler] = {}


def register_action(source: str, handler: ActionHandler) -> None:
    _handlers[source] = handler


def handler_for(source: str) -> ActionHandler | None:
    return _handlers.get(source)
