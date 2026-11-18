"""Uploads and downloads of attachments. See heinzel_api.files."""

from typing import Annotated
from urllib.parse import quote, unquote
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel

from heinzel_api import audit, files
from heinzel_api.db import tenant_session
from heinzel_api.deps import DbDep, ManifestsDep, PrincipalDep, TenantDep, client_ip
from heinzel_api.models import Attachment

router = APIRouter(prefix="/api/v1/files", tags=["files"])


class AttachmentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    size: int
    url: str
    is_image: bool


def attachment_out(att: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=str(att.id),
        filename=att.filename,
        content_type=att.content_type,
        size=att.size,
        url=f"/api/v1/files/{att.id}",
        is_image=att.content_type in files.IMAGE_TYPES,
    )


@router.post("", response_model=AttachmentOut, status_code=201)
async def upload(
    request: Request,
    p: PrincipalDep,
    tenant: TenantDep,
    db: DbDep,
    manifests: ManifestsDep,
    module: str,
    x_filename: Annotated[str | None, Header()] = None,
) -> AttachmentOut:
    """Body: the file itself. `module`: the module the file is for (the user must be able to
    use it). The file stays private to the uploader until the module links it."""
    m = manifests.get(module)
    install = next((i for i in tenant.config.modules if i.key == module), None)
    if m is None or install is None or not install.enabled:
        raise HTTPException(status_code=404, detail="unknown_module")
    if not {perm.id for perm in m.permissions} & p.permissions:
        raise HTTPException(status_code=403, detail="forbidden")
    settings = request.app.state.settings
    max_bytes = settings.upload_max_mb * 1024 * 1024
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > max_bytes:
        raise HTTPException(status_code=413, detail="file_too_large")
    data = await request.body()
    try:
        with tenant_session(db, tenant.id) as s:
            att = files.store_upload(
                s,
                request.app.state.storage,
                request.app.state.scanner,
                tenant_id=tenant.id,
                user_id=p.user_id,
                module=module,
                filename=unquote(x_filename) if x_filename else None,
                data=data,
                max_bytes=max_bytes,
            )
            audit.record(
                s,
                tenant.id,
                "file.uploaded",
                actor_user_id=p.user_id,
                target_type="attachment",
                target_id=str(att.id),
                data={"module": module, "filename": att.filename, "size": att.size},
                ip=client_ip(request),
            )
            return attachment_out(att)
    except files.UploadRejected as e:
        status = {"file_too_large": 413, "file_type": 415}.get(e.code, 422)
        if e.code == "file_infected":
            with tenant_session(db, tenant.id) as s:
                audit.record(
                    s,
                    tenant.id,
                    "file.rejected_infected",
                    actor_user_id=p.user_id,
                    data={"module": module},
                    ip=client_ip(request),
                )
        raise HTTPException(status_code=status, detail=e.code) from e
    except files.ScanUnavailable as e:
        raise HTTPException(status_code=503, detail="scan_unavailable") from e


@router.get("/{attachment_id}")
def download(
    attachment_id: UUID,
    request: Request,
    p: PrincipalDep,
    tenant: TenantDep,
    db: DbDep,
    download: bool = False,
) -> Response:
    with tenant_session(db, tenant.id) as s:
        att = s.get(Attachment, attachment_id)
        # Not found and not allowed look the same.
        if att is None or not files.can_view(s, att, p.user_id):
            raise HTTPException(status_code=404, detail="not_found")
        key, ctype, name, sha = att.storage_key, att.content_type, att.filename, att.sha256
    if request.headers.get("if-none-match") == f'"{sha[:16]}"':
        return Response(status_code=304)
    data = request.app.state.storage.get(key)
    inline = ctype in files.IMAGE_TYPES and ctype != "image/heic" and not download
    disposition = "inline" if inline else "attachment"
    return Response(
        content=data,
        media_type=ctype,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}",
            "ETag": f'"{sha[:16]}"',
            "Cache-Control": "private, max-age=3600",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )
