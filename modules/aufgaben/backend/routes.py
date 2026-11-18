"""Aufgaben API, mounted by the core under /api/v1/aufgaben."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from heinzel_api import localization, modules
from heinzel_api.db import tenant_session
from heinzel_api.deps import Principal, TenantContext, client_ip, current_tenant, require
from heinzel_api.models import User
from heinzel_api.routes.files import AttachmentOut, attachment_out
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service as svc
from .models import Task, TaskList

router = APIRouter(tags=["aufgaben"])

UseDep = Annotated[Principal, Depends(require(svc.USE))]
TenantDep = Annotated[TenantContext, Depends(current_tenant)]


def _actor(request: Request, p: Principal, tenant: TenantContext) -> svc.Actor:
    manifest = request.app.state.manifests[svc.MODULE]
    loc = localization.effective(tenant.config, p.preferences)
    return svc.Actor(
        tenant_id=tenant.id,
        tenant=tenant.config,
        user_id=p.user_id,
        settings=modules.settings_for(tenant.config, manifest),
        today=svc.today_in(loc["timezone"]),
        ip=client_ip(request),
        can_share=p.can(svc.SHARE),
    )


@contextmanager
def _session(request: Request, actor: svc.Actor) -> Iterator[Session]:
    """A tenant transaction; service errors become HTTP errors (after rollback)."""
    try:
        with tenant_session(request.app.state.db, actor.tenant_id) as s:
            yield s
    except svc.NotFound as e:
        raise HTTPException(status_code=404, detail="not_found") from e
    except svc.Forbidden as e:
        raise HTTPException(status_code=403, detail="forbidden") from e
    except svc.Invalid as e:
        raise HTTPException(status_code=422, detail=e.code) from e


# --- models -----------------------------------------------------------------------------------


class Person(BaseModel):
    id: str
    display_name: str
    initials: str


def _person(u: User | None) -> Person | None:
    if u is None:
        return None
    parts = [x for x in u.display_name.split() if x]
    return Person(
        id=str(u.id),
        display_name=u.display_name,
        initials="".join(x[0] for x in parts[:2]).upper() or "?",
    )


class ListOut(BaseModel):
    id: str
    name: str
    kind: Literal["personal", "shared"]
    role: Literal["owner", "member"]
    open: int
    members: int


class ListsOut(BaseModel):
    lists: list[ListOut]
    can_share: bool
    assign_scope: str
    open: int
    done: int


class TaskOut(BaseModel):
    id: str
    list_id: str
    list_name: str
    list_kind: str
    title: str
    note: str
    due_date: date | None
    due_label: str
    due_tone: Literal["over", "today", "none", ""]
    status: Literal["open", "done"]
    done_at: datetime | None
    done_by: Person | None
    assignee: Person | None
    created_by: Person | None
    created_at: datetime
    images: int
    can_delete: bool


class TaskDetail(TaskOut):
    attachments: list[AttachmentOut]
    assignable: list[Person]


class TasksOut(BaseModel):
    tasks: list[TaskOut]
    open: int
    done: int


def _tone(t: Task, today: date) -> str:
    if t.status == "done":
        return ""
    if t.due_date is None:
        return "none"
    if t.due_date < today:
        return "over"
    return "today" if t.due_date == today else ""


def _task_outs(s: Session, actor: svc.Actor, rows: list[Task]) -> list[TaskOut]:
    list_ids = {t.list_id for t in rows}
    lists = {lst.id: lst for lst in s.scalars(select(TaskList).where(TaskList.id.in_(list_ids)))}
    member_of = {
        lst_id for lst_id in list_ids if svc.member_role(s, lst_id, actor.user_id) is not None
    }
    user_ids = {u for t in rows for u in (t.assignee_id, t.created_by, t.done_by) if u}
    users = {u.id: u for u in s.scalars(select(User).where(User.id.in_(user_ids)))}
    imgs = svc.image_counts(s, [t.id for t in rows])
    out = []
    for t in rows:
        lst = lists[t.list_id]
        out.append(
            TaskOut(
                id=str(t.id),
                list_id=str(lst.id),
                list_name=svc.list_name(lst, actor.settings),
                list_kind=lst.kind,
                title=t.title,
                note=t.note,
                due_date=t.due_date,
                due_label="Erledigt"
                if t.status == "done"
                else svc.due_label(t.due_date, actor.today),
                due_tone=_tone(t, actor.today),
                status=t.status,
                done_at=t.done_at,
                done_by=_person(users.get(t.done_by)),
                assignee=_person(users.get(t.assignee_id)),
                created_by=_person(users.get(t.created_by)),
                created_at=t.created_at,
                images=imgs.get(str(t.id), 0),
                can_delete=t.list_id in member_of,
            )
        )
    return out


def _assignable(s: Session, actor: svc.Actor, lst: TaskList) -> list[Person]:
    if actor.settings.get("assign_scope") == "tenant":
        users = s.scalars(select(User).where(User.status == "active").order_by(User.display_name))
        return [_person(u) for u in users]
    return [_person(u) for u, _role in svc.members(s, lst.id) if u.status == "active"]


def _detail(s: Session, actor: svc.Actor, task: Task, lst: TaskList) -> TaskDetail:
    base = _task_outs(s, actor, [task])[0]
    return TaskDetail(
        **base.model_dump(),
        attachments=[attachment_out(a) for a in svc.images(s, task)],
        assignable=_assignable(s, actor, lst),
    )


# --- lists ------------------------------------------------------------------------------------


@router.get("/lists", response_model=ListsOut)
def get_lists(request: Request, p: UseDep, tenant: TenantDep) -> ListsOut:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        out = []
        for lst, role in svc.my_lists(s, actor):
            open_, _ = svc.counts(s, actor, lst.id)
            out.append(
                ListOut(
                    id=str(lst.id),
                    name=svc.list_name(lst, actor.settings),
                    kind=lst.kind,
                    role=role,
                    open=open_,
                    members=len(svc.members(s, lst.id)),
                )
            )
        open_all, done_all = svc.counts(s, actor)
        return ListsOut(
            lists=out,
            can_share=actor.can_share and actor.settings.get("shared_lists_enabled", True),
            assign_scope=actor.settings.get("assign_scope", "list_members"),
            open=open_all,
            done=done_all,
        )


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.post("/lists", response_model=ListOut, status_code=201)
def create_list(body: ListIn, request: Request, p: UseDep, tenant: TenantDep) -> ListOut:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        lst = svc.create_list(s, actor, body.name)
        return ListOut(
            id=str(lst.id), name=lst.name, kind="shared", role="owner", open=0, members=1
        )


@router.put("/lists/{list_id}", response_model=ListOut)
def rename_list(
    list_id: uuid.UUID, body: ListIn, request: Request, p: UseDep, tenant: TenantDep
) -> ListOut:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        lst = svc.rename_list(s, actor, list_id, body.name)
        open_, _ = svc.counts(s, actor, lst.id)
        return ListOut(
            id=str(lst.id),
            name=lst.name,
            kind="shared",
            role="owner",
            open=open_,
            members=len(svc.members(s, lst.id)),
        )


@router.delete("/lists/{list_id}", status_code=204)
def delete_list(list_id: uuid.UUID, request: Request, p: UseDep, tenant: TenantDep) -> None:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        svc.delete_list(s, actor, list_id, request.app.state.storage)


class MemberOut(Person):
    role: str


@router.get("/lists/{list_id}/members", response_model=list[MemberOut])
def get_members(
    list_id: uuid.UUID, request: Request, p: UseDep, tenant: TenantDep
) -> list[MemberOut]:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        svc.get_list(s, actor, list_id)
        return [
            MemberOut(**_person(u).model_dump(), role=role) for u, role in svc.members(s, list_id)
        ]


class MemberIn(BaseModel):
    user_id: uuid.UUID


@router.post("/lists/{list_id}/members", status_code=204)
def add_member(
    list_id: uuid.UUID, body: MemberIn, request: Request, p: UseDep, tenant: TenantDep
) -> None:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        svc.add_member(s, actor, list_id, body.user_id)


@router.delete("/lists/{list_id}/members/{user_id}", status_code=204)
def remove_member(
    list_id: uuid.UUID, user_id: uuid.UUID, request: Request, p: UseDep, tenant: TenantDep
) -> None:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        svc.remove_member(s, actor, list_id, user_id)


@router.get("/people", response_model=list[Person])
def people(
    request: Request, p: UseDep, tenant: TenantDep, q: str = Query("", max_length=100)
) -> list[Person]:
    """Active people of the tenant, for adding list members (directory light)."""
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        stmt = select(User).where(User.status == "active").order_by(User.display_name).limit(20)
        if q.strip():
            like = f"%{q.strip()}%"
            stmt = stmt.where(User.display_name.ilike(like) | User.email.ilike(like))
        return [_person(u) for u in s.scalars(stmt)]


# --- tasks ------------------------------------------------------------------------------------


@router.get("/tasks", response_model=TasksOut)
def get_tasks(
    request: Request,
    p: UseDep,
    tenant: TenantDep,
    list_id: Annotated[uuid.UUID | None, Query(alias="list")] = None,
    done: bool = False,
) -> TasksOut:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        rows = svc.tasks(s, actor, list_id, include_done=done)
        open_, done_ = svc.counts(s, actor, list_id)
        return TasksOut(tasks=_task_outs(s, actor, rows), open=open_, done=done_)


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    list_id: uuid.UUID | None = None
    due_date: date | None = None
    assignee_id: uuid.UUID | None = None
    note: str = Field("", max_length=10000)


@router.post("/tasks", response_model=TaskDetail, status_code=201)
def create_task(body: TaskIn, request: Request, p: UseDep, tenant: TenantDep) -> TaskDetail:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        task = svc.create_task(s, actor, **body.model_dump())
        return _detail(s, actor, task, s.get(TaskList, task.list_id))


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(task_id: uuid.UUID, request: Request, p: UseDep, tenant: TenantDep) -> TaskDetail:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        task, lst, _ = svc.get_task(s, actor, task_id)
        return _detail(s, actor, task, lst)


class TaskPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    note: str | None = Field(None, max_length=10000)
    due_date: date | None = None
    assignee_id: uuid.UUID | None = None
    list_id: uuid.UUID | None = None


@router.patch("/tasks/{task_id}", response_model=TaskDetail)
def update_task(
    task_id: uuid.UUID, body: TaskPatch, request: Request, p: UseDep, tenant: TenantDep
) -> TaskDetail:
    """Only the fields sent change; send null to clear due_date or assignee_id."""
    actor = _actor(request, p, tenant)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("list_id", 0) is None:
        raise HTTPException(status_code=422, detail="list_required")
    with _session(request, actor) as s:
        task, lst = svc.update_task(s, actor, task_id, changes)
        return _detail(s, actor, task, lst)


@router.post("/tasks/{task_id}/complete", response_model=TaskDetail)
def complete(task_id: uuid.UUID, request: Request, p: UseDep, tenant: TenantDep) -> TaskDetail:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        task = svc.complete(s, actor, task_id)
        return _detail(s, actor, task, s.get(TaskList, task.list_id))


@router.post("/tasks/{task_id}/reopen", response_model=TaskDetail)
def reopen(task_id: uuid.UUID, request: Request, p: UseDep, tenant: TenantDep) -> TaskDetail:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        task = svc.reopen(s, actor, task_id)
        return _detail(s, actor, task, s.get(TaskList, task.list_id))


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: uuid.UUID, request: Request, p: UseDep, tenant: TenantDep) -> None:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        svc.delete_task(s, actor, task_id, request.app.state.storage)


class ImagesIn(BaseModel):
    attachment_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)


@router.post("/tasks/{task_id}/images", response_model=TaskDetail)
def add_images(
    task_id: uuid.UUID, body: ImagesIn, request: Request, p: UseDep, tenant: TenantDep
) -> TaskDetail:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        svc.add_images(s, actor, task_id, body.attachment_ids)
        task, lst, _ = svc.get_task(s, actor, task_id)
        return _detail(s, actor, task, lst)


@router.delete("/tasks/{task_id}/images/{attachment_id}", response_model=TaskDetail)
def remove_image(
    task_id: uuid.UUID, attachment_id: uuid.UUID, request: Request, p: UseDep, tenant: TenantDep
) -> TaskDetail:
    actor = _actor(request, p, tenant)
    with _session(request, actor) as s:
        svc.remove_image(s, actor, task_id, attachment_id, request.app.state.storage)
        task, lst, _ = svc.get_task(s, actor, task_id)
        return _detail(s, actor, task, lst)
