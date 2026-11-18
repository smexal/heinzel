"""In-process events between the core and modules.

`publish()` runs every subscribed handler synchronously, inside the publisher's transaction
and tenant scope, so a handler's changes commit or roll back together with the cause.
Handlers must be quick; slow work belongs in a scheduled job.

Core events:
    core.user.deactivated   user_id, actor_user_id
"""

import logging
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

Handler = Callable[[Session, uuid.UUID, dict[str, Any]], None]

# event -> subscriber key (e.g. the module id) -> handler; re-subscribing replaces
_subscribers: dict[str, dict[str, Handler]] = {}


def subscribe(event: str, key: str, handler: Handler) -> None:
    _subscribers.setdefault(event, {})[key] = handler


def publish(session: Session, tenant_id: uuid.UUID, event: str, **payload: Any) -> None:
    for key, handler in list(_subscribers.get(event, {}).items()):
        log.debug("event %s -> %s", event, key)
        handler(session, tenant_id, payload)
