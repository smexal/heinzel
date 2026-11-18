"""Files service: uploads, storage, virus scan and access checks for attachments.

Bytes live in a storage backend, metadata in core.attachment. The only backend today is a
local directory (HEINZEL_FILES_DIR; a Docker volume in the stack). Storage keys are
backend-neutral (`<tenant>/<yyyy>/<mm>/<attachment id>`) and the database holds size and
sha256 of every file, so the files can later be moved to another backend (a self-hosted or
Swiss S3-compatible store, a NAS) with `heinzel files copy` and checked with
`heinzel files verify`. A module uploads first (the file is "staged": no target yet,
visible only to the uploader), then links it to its own object. Who may see a linked file
is decided by the module through a registered access check; recipients of an inbox item
that shows the file may see it too.
"""

import hashlib
import socket
import struct
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import any_, select
from sqlalchemy.orm import Session

from heinzel_api.models import Attachment, InboxItem

if TYPE_CHECKING:
    from heinzel_api.config import Settings

# --- content types (sniffed from the bytes, never taken from the client) ----------------------

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/heic"}
DOCUMENT_TYPES = {"application/pdf"}
ALLOWED_TYPES = IMAGE_TYPES | DOCUMENT_TYPES


def sniff(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"heif"):
        return "image/heic"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def clean_filename(name: str | None, content_type: str) -> str:
    ext = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
        "image/heic": "heic",
        "application/pdf": "pdf",
    }[content_type]
    base = (name or "").replace("\\", "/").split("/")[-1].strip()
    base = "".join(c for c in base if c.isprintable() and c not in '<>:"|?*')[:200]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return f"{stem or 'datei'}.{ext}"


# --- storage --------------------------------------------------------------------------------


class Storage(Protocol):
    """A key/value store for file bytes. Keys look like `<tenant>/<yyyy>/<mm>/<uuid>`."""

    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def iter_keys(self) -> Iterator[str]: ...


class LocalStorage:
    """Files under one directory. Keys are generated here, never taken from requests."""

    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("invalid storage key")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def iter_keys(self) -> Iterator[str]:
        if not self.root.is_dir():
            return
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                yield path.relative_to(self.root).as_posix()


class MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.blobs[key] = data

    def get(self, key: str) -> bytes:
        return self.blobs[key]

    def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.blobs

    def iter_keys(self) -> Iterator[str]:
        yield from sorted(self.blobs)


def make_storage(settings: "Settings") -> Storage:
    """The configured backend. Add new backends here; keys and metadata stay the same."""
    if settings.storage == "local":
        return LocalStorage(settings.files_dir)
    raise ValueError(f"unknown storage backend {settings.storage!r}")


# --- virus scan -------------------------------------------------------------------------------


class ScanUnavailable(Exception):
    pass


class Scanner(Protocol):
    def scan(self, data: bytes) -> str: ...  # "clean" | "infected" | "skipped"


class NoScanner:
    def scan(self, data: bytes) -> str:
        return "skipped"


class ClamdScanner:
    """clamd INSTREAM protocol over TCP."""

    def __init__(self, host: str, port: int = 3310, timeout: float = 30.0):
        self.host, self.port, self.timeout = host, port, timeout

    def scan(self, data: bytes) -> str:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.sendall(b"zINSTREAM\0")
                for i in range(0, len(data), 64 * 1024):
                    chunk = data[i : i + 64 * 1024]
                    sock.sendall(struct.pack("!L", len(chunk)) + chunk)
                sock.sendall(struct.pack("!L", 0))
                reply = b""
                while not reply.endswith(b"\0"):
                    part = sock.recv(4096)
                    if not part:
                        break
                    reply += part
        except OSError as e:
            raise ScanUnavailable(str(e)) from e
        text = reply.rstrip(b"\0").decode(errors="replace")
        if text.endswith("OK"):
            return "clean"
        if text.endswith("FOUND"):
            return "infected"
        raise ScanUnavailable(text)


# --- service ----------------------------------------------------------------------------------


class UploadRejected(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def store_upload(
    session: Session,
    storage: Storage,
    scanner: Scanner,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    module: str,
    filename: str | None,
    data: bytes,
    max_bytes: int,
    allowed: set[str] = ALLOWED_TYPES,
) -> Attachment:
    """Check, scan and store an upload. The attachment is staged until a module links it."""
    if not data:
        raise UploadRejected("empty_file")
    if len(data) > max_bytes:
        raise UploadRejected("file_too_large")
    ctype = sniff(data)
    if ctype is None or ctype not in allowed:
        raise UploadRejected("file_type")
    status = scanner.scan(data)  # may raise ScanUnavailable
    if status == "infected":
        raise UploadRejected("file_infected")
    att_id = uuid.uuid4()
    now = datetime.now(UTC)
    key = f"{tenant_id}/{now:%Y/%m}/{att_id}"
    storage.put(key, data)
    att = Attachment(
        id=att_id,
        tenant_id=tenant_id,
        module=module,
        filename=clean_filename(filename, ctype),
        content_type=ctype,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=key,
        scan_status=status,
        created_by=user_id,
    )
    session.add(att)
    session.flush()
    return att


def link(
    session: Session,
    attachment_ids: list[uuid.UUID],
    *,
    module: str,
    target_type: str,
    target_id: str,
    user_id: uuid.UUID,
) -> list[Attachment]:
    """Attach staged uploads of this user and module to a module object."""
    rows = list(
        session.scalars(
            select(Attachment).where(
                Attachment.id.in_(attachment_ids), Attachment.deleted_at.is_(None)
            )
        )
    )
    if len(rows) != len(set(attachment_ids)):
        raise UploadRejected("unknown_attachment")
    for att in rows:
        staged_by_user = att.target_id is None and att.created_by == user_id
        same_target = att.target_type == target_type and att.target_id == target_id
        if att.module != module or not (staged_by_user or same_target):
            raise UploadRejected("attachment_not_linkable")
        att.target_type, att.target_id = target_type, target_id
    session.flush()
    return rows


def delete(session: Session, storage: Storage, att: Attachment) -> None:
    """Remove one file: bytes from storage, the row stays marked deleted (audit trail)."""
    storage.delete(att.storage_key)
    att.deleted_at = datetime.now(UTC)
    session.flush()


def for_target(
    session: Session, *, module: str, target_type: str, target_id: str
) -> list[Attachment]:
    """Live attachments of one module object, oldest first."""
    return list(
        session.scalars(
            select(Attachment)
            .where(
                Attachment.module == module,
                Attachment.target_type == target_type,
                Attachment.target_id == target_id,
                Attachment.deleted_at.is_(None),
            )
            .order_by(Attachment.created_at)
        )
    )


def delete_for_target(
    session: Session, storage: Storage, *, module: str, target_type: str, target_id: str
) -> int:
    rows = list(
        session.scalars(
            select(Attachment).where(
                Attachment.module == module,
                Attachment.target_type == target_type,
                Attachment.target_id == target_id,
                Attachment.deleted_at.is_(None),
            )
        )
    )
    now = datetime.now(UTC)
    for att in rows:
        storage.delete(att.storage_key)
        att.deleted_at = now
    session.flush()
    return len(rows)


# Modules register who may see files linked to their objects:
#   register_access("aufgaben", "task", lambda session, user_id, target_id: ...)
AccessCheck = Callable[[Session, uuid.UUID, str], bool]
_access: dict[tuple[str, str], AccessCheck] = {}


def register_access(module: str, target_type: str, check: AccessCheck) -> None:
    _access[(module, target_type)] = check


def can_view(session: Session, att: Attachment, user_id: uuid.UUID) -> bool:
    if att.deleted_at is not None or att.scan_status not in ("clean", "skipped"):
        return False
    if att.created_by == user_id:
        return True
    shown_in_inbox = session.scalar(
        select(InboxItem.id)
        .where(InboxItem.user_id == user_id, any_(InboxItem.attachments) == att.id)
        .limit(1)
    )
    if shown_in_inbox:
        return True
    if att.target_type and att.target_id:
        check = _access.get((att.module, att.target_type))
        if check is not None:
            return check(session, user_id, att.target_id)
    return False
