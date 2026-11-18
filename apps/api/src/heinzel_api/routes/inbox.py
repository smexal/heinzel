"""Mein Eingang: the signed-in user's tasks and notices."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update

from heinzel_api import audit, inbox
from heinzel_api.db import tenant_session
from heinzel_api.deps import DbDep, ManifestsDep, PrincipalDep, TenantDep, client_ip
from heinzel_api.models import Attachment, InboxItem, User
from heinzel_api.routes.files import AttachmentOut, attachment_out

router = APIRouter(prefix="/api/v1/inbox", tags=["inbox"])

View = Literal["open", "notices", "done"]
CORE_LABEL = "Administration"


class InboxItemOut(BaseModel):
    id: str
    source: str
    source_label: str
    kind: str
    severity: str | None
    title: str
    context: str | None
    body: str | None
    reason: str | None
    facts: list[dict[str, str]]
    link: str | None
    actions: list[dict[str, str]]
    attachments: list[AttachmentOut]
    actor_name: str | None
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    read: bool
    done: bool


class InboxPage(BaseModel):
    items: list[InboxItemOut]
    counts: dict[str, int]
    sources: list[dict[str, str]]


def _labels(manifests) -> dict[str, str]:
    out = {inbox.CORE: CORE_LABEL}
    for m in manifests.values():
        out[m.id] = m.name.get("de") or next(iter(m.name.values()), m.id)
    return out


def _out(s, items: list[InboxItem], labels: dict[str, str]) -> list[InboxItemOut]:
    actor_ids = {i.actor_user_id for i in items if i.actor_user_id}
    names = (
        dict(s.execute(select(User.id, User.display_name).where(User.id.in_(actor_ids))).all())
        if actor_ids
        else {}
    )
    att_ids = {a for i in items for a in i.attachments}
    atts = (
        {
            a.id: a
            for a in s.scalars(
                select(Attachment).where(
                    Attachment.id.in_(att_ids), Attachment.deleted_at.is_(None)
                )
            )
        }
        if att_ids
        else {}
    )
    return [
        InboxItemOut(
            id=str(i.id),
            source=i.source,
            source_label=labels.get(i.source, i.source),
            kind=i.kind,
            severity=i.severity,
            title=i.title,
            context=i.context,
            body=i.body,
            reason=i.reason,
            facts=i.facts,
            link=i.link,
            actions=i.actions if i.done_at is None else [],
            attachments=[attachment_out(atts[a]) for a in i.attachments if a in atts],
            actor_name=names.get(i.actor_user_id) if i.actor_user_id else None,
            due_at=i.due_at,
            created_at=i.created_at,
            updated_at=i.updated_at,
            read=i.read_at is not None,
            done=i.done_at is not None,
        )
        for i in items
    ]


def counts(s, user_id: UUID) -> dict[str, int]:
    rows = s.execute(
        select(InboxItem.kind, InboxItem.read_at.is_(None), func.count())
        .where(InboxItem.user_id == user_id, InboxItem.done_at.is_(None))
        .group_by(InboxItem.kind, InboxItem.read_at.is_(None))
    ).all()
    c = {"open": 0, "tasks": 0, "notices": 0, "unread": 0}
    for kind, unread, n in rows:
        c["open"] += n
        c["tasks" if kind == "task" else "notices"] += n
        if unread:
            c["unread"] += n
    return c


@router.get("", response_model=InboxPage)
def list_items(
    p: PrincipalDep,
    tenant: TenantDep,
    db: DbDep,
    manifests: ManifestsDep,
    view: View = "open",
    source: str | None = None,
    limit: int = 100,
) -> InboxPage:
    labels = _labels(manifests)
    with tenant_session(db, tenant.id) as s:
        stmt = select(InboxItem).where(InboxItem.user_id == p.user_id)
        if view == "done":
            stmt = stmt.where(InboxItem.done_at.is_not(None)).order_by(InboxItem.done_at.desc())
        else:
            stmt = stmt.where(InboxItem.done_at.is_(None))
            if view == "notices":
                stmt = stmt.where(InboxItem.kind == "notice")
            # Tasks first, unread before read, newest first.
            stmt = stmt.order_by(
                (InboxItem.kind == "task").desc(),
                InboxItem.read_at.is_(None).desc(),
                InboxItem.updated_at.desc(),
            )
        if source:
            stmt = stmt.where(InboxItem.source == source)
        items = list(s.scalars(stmt.limit(min(max(limit, 1), 200))))
        used = s.scalars(select(InboxItem.source).where(InboxItem.user_id == p.user_id).distinct())
        return InboxPage(
            items=_out(s, items, labels),
            counts=counts(s, p.user_id),
            sources=[{"key": k, "label": labels.get(k, k)} for k in sorted(used)],
        )


def _own(s, item_id: UUID, user_id: UUID) -> InboxItem:
    item = s.get(InboxItem, item_id)
    if item is None or item.user_id != user_id:
        raise HTTPException(status_code=404, detail="not_found")
    return item


@router.post("/{item_id}/{change}", response_model=InboxItemOut)
def change_state(
    item_id: UUID,
    change: Literal["read", "unread", "done", "reopen"],
    p: PrincipalDep,
    tenant: TenantDep,
    db: DbDep,
    manifests: ManifestsDep,
) -> InboxItemOut:
    now = datetime.now(UTC)
    with tenant_session(db, tenant.id) as s:
        item = _own(s, item_id, p.user_id)
        if change == "read":
            item.read_at = item.read_at or now
        elif change == "unread":
            item.read_at = None
        elif change == "done":
            item.done_at = item.done_at or now
            item.read_at = item.read_at or now
        else:
            item.done_at = None
        s.flush()
        return _out(s, [item], _labels(manifests))[0]


@router.post("/read-all", response_model=dict)
def read_all(p: PrincipalDep, tenant: TenantDep, db: DbDep, source: str | None = None) -> dict:
    with tenant_session(db, tenant.id) as s:
        stmt = (
            update(InboxItem)
            .where(
                InboxItem.user_id == p.user_id,
                InboxItem.done_at.is_(None),
                InboxItem.read_at.is_(None),
            )
            .values(read_at=datetime.now(UTC))
        )
        if source:
            stmt = stmt.where(InboxItem.source == source)
        n = s.execute(stmt).rowcount or 0
    return {"marked": n}


@router.post("/{item_id}/actions/{key}", response_model=dict[str, Any])
def run_action(
    item_id: UUID,
    key: str,
    request: Request,
    p: PrincipalDep,
    tenant: TenantDep,
    db: DbDep,
) -> dict[str, Any]:
    with tenant_session(db, tenant.id) as s:
        item = _own(s, item_id, p.user_id)
        if item.done_at is not None or key not in {a["key"] for a in item.actions}:
            raise HTTPException(status_code=409, detail="action_unavailable")
        handler = inbox.handler_for(item.source)
        if handler is None:
            raise HTTPException(status_code=409, detail="action_unavailable")
        try:
            message = handler(s, item, key, p.user_id)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail="forbidden") from e
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e) or "action_failed") from e
        audit.record(
            s,
            tenant.id,
            "inbox.action",
            actor_user_id=p.user_id,
            target_type="inbox_item",
            target_id=str(item.id),
            data={"source": item.source, "action": key, "ref": [item.ref_type, item.ref_id]},
            ip=client_ip(request),
        )
    return {"message": message}
