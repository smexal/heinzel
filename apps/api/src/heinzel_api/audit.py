"""Audit log: append-only and hash-chained per tenant.

Each event stores the hash of its predecessor (same tenant) and its own hash over a
canonical JSON form of its content. Changing or deleting a row breaks the chain, which
`verify_chain()` detects. Writers serialise per tenant with an advisory lock, so the
chain never forks. Events are written in the same transaction as the change they record.
"""

import hashlib
import ipaddress
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from heinzel_api.models import AuditEvent

GENESIS = "0" * 64
CHANNELS = {"web", "api", "mcp", "system", "cli"}


def _canonical(event: AuditEvent) -> bytes:
    at = event.at.astimezone(UTC).isoformat(timespec="microseconds")
    body = {
        "tenant_id": str(event.tenant_id),
        "at": at,
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "channel": event.channel,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "data": event.data,
        "ip": str(event.ip) if event.ip else None,
        "prev_hash": event.prev_hash,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hash(event: AuditEvent) -> str:
    return hashlib.sha256(_canonical(event)).hexdigest()


def record(
    session: Session,
    tenant_id: UUID,
    action: str,
    *,
    actor_user_id: UUID | None = None,
    channel: str = "web",
    target_type: str | None = None,
    target_id: str | None = None,
    data: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditEvent:
    """Append an event to the tenant's chain inside the caller's transaction."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown audit channel '{channel}'")
    session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"audit:{tenant_id}"}
    )
    prev = session.scalar(
        select(AuditEvent.hash)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.id.desc())
        .limit(1)
    )
    event = AuditEvent(
        tenant_id=tenant_id,
        at=datetime.now(UTC),
        actor_user_id=actor_user_id,
        channel=channel,
        action=action,
        target_type=target_type,
        target_id=target_id,
        # Round-trip through JSON so the stored jsonb and the hashed form agree.
        data=json.loads(json.dumps(data or {}, default=str)),
        # Normalise so the value read back from inet hashes the same.
        ip=str(ipaddress.ip_address(ip)) if ip else None,
        prev_hash=prev or GENESIS,
    )
    event.hash = _hash(event)
    session.add(event)
    session.flush()
    return event


@dataclass
class ChainCheck:
    ok: bool
    events: int
    broken_at: int | None = None
    reason: str | None = None


def verify_chain(session: Session, tenant_id: UUID) -> ChainCheck:
    prev = GENESIS
    count = 0
    rows = session.scalars(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.id)
    )
    for event in rows:
        count += 1
        if event.prev_hash != prev:
            return ChainCheck(False, count, event.id, "prev_hash does not match predecessor")
        if _hash(event) != event.hash:
            return ChainCheck(False, count, event.id, "content does not match hash")
        prev = event.hash
    return ChainCheck(True, count)
