"""Administration: audit log viewer and export (permission core.audit.read)."""

import csv
import io
import json
import time
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Select, String, cast, or_, select
from sqlalchemy.orm import Session

from heinzel_api import audit
from heinzel_api.db import tenant_session
from heinzel_api.deps import DbDep, Principal, TenantContext, TenantDep, client_ip, require
from heinzel_api.models import AuditEvent, User

router = APIRouter(prefix="/api/v1/admin/audit", tags=["admin"])

AuditReader = Annotated[Principal, Depends(require("core.audit.read"))]

PAGE_MAX = 200
EXPORT_MAX = 50_000
CHAIN_CHECK_EVERY_S = 600


class AuditEventOut(BaseModel):
    id: int
    at: datetime
    actor_user_id: str | None
    actor_name: str | None
    channel: str
    action: str
    target_type: str | None
    target_id: str | None
    target_name: str | None
    data: dict[str, Any]
    ip: str | None
    hash: str
    prev_hash: str


class ChainStatus(BaseModel):
    ok: bool
    events: int
    checked_at: datetime
    broken_at: int | None = None


class AuditPage(BaseModel):
    events: list[AuditEventOut]
    next_before_id: int | None
    chain: ChainStatus
    actors: list[dict[str, str]]  # people who appear in the log, for the filter


class Filters(BaseModel):
    q: str | None = None
    actor: str | None = None
    channel: str | None = None
    area: str | None = None  # "core" or a module id: matches the action prefix
    since: datetime | None = None


def _filters(
    q: Annotated[str | None, Query(max_length=200)] = None,
    actor: Annotated[str | None, Query(max_length=40)] = None,
    channel: Annotated[str | None, Query(max_length=20)] = None,
    area: Annotated[str | None, Query(max_length=40)] = None,
    since: datetime | None = None,
) -> Filters:
    return Filters(q=q, actor=actor, channel=channel, area=area, since=since)


FiltersDep = Annotated[Filters, Depends(_filters)]

# Actions of the core live under these prefixes; everything else is "<module>.…".
CORE_PREFIXES = ("auth.", "user.", "tenant.", "role.", "audit.", "settings.", "module.")


def _apply(stmt: Select, f: Filters) -> Select:
    if f.actor:
        stmt = stmt.where(cast(AuditEvent.actor_user_id, String) == f.actor)
    if f.channel:
        stmt = stmt.where(AuditEvent.channel == f.channel)
    if f.area == "core":
        stmt = stmt.where(or_(*[AuditEvent.action.startswith(p) for p in CORE_PREFIXES]))
    elif f.area:
        stmt = stmt.where(AuditEvent.action.startswith(f"{f.area}."))
    if f.since:
        stmt = stmt.where(AuditEvent.at >= f.since)
    if f.q:
        like = f"%{f.q.strip()}%"
        stmt = stmt.where(
            or_(
                AuditEvent.action.ilike(like),
                AuditEvent.target_id.ilike(like),
                cast(AuditEvent.data, String).ilike(like),
                cast(AuditEvent.id, String) == f.q.strip(),
            )
        )
    return stmt


def _names(s: Session, events: list[AuditEvent]) -> dict[str, str]:
    ids = {str(e.actor_user_id) for e in events if e.actor_user_id}
    ids |= {e.target_id for e in events if e.target_type == "user" and e.target_id}
    if not ids:
        return {}
    rows = s.execute(select(User.id, User.display_name).where(cast(User.id, String).in_(ids)))
    return {str(uid): name for uid, name in rows}


def _out(e: AuditEvent, names: dict[str, str]) -> AuditEventOut:
    actor = str(e.actor_user_id) if e.actor_user_id else None
    return AuditEventOut(
        id=e.id,
        at=e.at,
        actor_user_id=actor,
        actor_name=names.get(actor) if actor else None,
        channel=e.channel,
        action=e.action,
        target_type=e.target_type,
        target_id=e.target_id,
        target_name=names.get(e.target_id) if e.target_type == "user" and e.target_id else None,
        data=e.data,
        ip=str(e.ip) if e.ip else None,
        hash=e.hash,
        prev_hash=e.prev_hash,
    )


def _chain(request: Request, s: Session, tenant: TenantContext) -> ChainStatus:
    """Verify the hash chain, at most every 10 minutes per tenant (the full check reads
    every event)."""
    cache: dict = request.app.state.audit_chain
    hit = cache.get(tenant.id)
    if hit and time.monotonic() - hit[0] < CHAIN_CHECK_EVERY_S:
        return hit[1]
    result = audit.verify_chain(s, tenant.id)
    status = ChainStatus(
        ok=result.ok,
        events=result.events,
        checked_at=datetime.now().astimezone(),
        broken_at=result.broken_at,
    )
    cache[tenant.id] = (time.monotonic(), status)
    return status


@router.get("", response_model=AuditPage)
def list_events(
    request: Request,
    actor: AuditReader,
    tenant: TenantDep,
    db: DbDep,
    f: FiltersDep,
    before_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=PAGE_MAX)] = 50,
) -> AuditPage:
    with tenant_session(db, tenant.id) as s:
        stmt = _apply(select(AuditEvent), f).order_by(AuditEvent.id.desc()).limit(limit + 1)
        if before_id is not None:
            stmt = stmt.where(AuditEvent.id < before_id)
        events = list(s.scalars(stmt))
        more = len(events) > limit
        events = events[:limit]
        names = _names(s, events)
        people = s.execute(
            select(User.id, User.display_name)
            .where(User.id.in_(select(AuditEvent.actor_user_id).distinct()))
            .order_by(User.display_name)
        )
        return AuditPage(
            events=[_out(e, names) for e in events],
            next_before_id=events[-1].id if more and events else None,
            chain=_chain(request, s, tenant),
            actors=[{"id": str(uid), "name": name} for uid, name in people],
        )


@router.get("/export.csv")
def export_csv(
    request: Request, actor: AuditReader, tenant: TenantDep, db: DbDep, f: FiltersDep
) -> StreamingResponse:
    """CSV of the filtered events (newest first). The export itself is audited."""
    with tenant_session(db, tenant.id) as s:
        events = list(
            s.scalars(
                _apply(select(AuditEvent), f).order_by(AuditEvent.id.desc()).limit(EXPORT_MAX)
            )
        )
        names = _names(s, events)
        audit.record(
            s,
            tenant.id,
            "audit.exported",
            actor_user_id=actor.user_id,
            data={"filters": f.model_dump(exclude_none=True, mode="json"), "rows": len(events)},
            ip=client_ip(request),
        )
    buf = io.StringIO()
    buf.write("﻿")  # BOM: Excel opens UTF-8 correctly
    w = csv.writer(buf, delimiter=";")
    w.writerow(["id", "zeit_utc", "person", "kanal", "aktion", "ziel_typ", "ziel", "daten", "ip"])
    for e in events:
        o = _out(e, names)
        w.writerow(
            [
                o.id,
                o.at.isoformat(),
                o.actor_name or o.actor_user_id or "",
                o.channel,
                o.action,
                o.target_type or "",
                o.target_name or o.target_id or "",
                json.dumps(o.data, ensure_ascii=False) if o.data else "",
                o.ip or "",
            ]
        )
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="audit-{stamp}.csv"'},
    )
