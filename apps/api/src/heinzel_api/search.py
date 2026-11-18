"""Global search: one index for core and module entities, filtered by permissions twice.

Modules keep their entities in the index with `index()` / `remove()` (in the same transaction
as the change) and register a provider with an optional `can_view` check:

    search.register_provider("aufgaben", "task", can_view=lambda s, user_id, ids: {...})

Label and icon of a provider come from the module manifest
(`contributes.search_providers: [{type, label, icon}]`).

A query runs in two steps: the index query only covers modules that are active for the tenant
(and not switched off with the module setting `search_enabled`) and documents whose
`permission` the user holds; then each provider's `can_view` checks every hit. Hidden hits are
never counted. Sensitive fields must never be indexed.

The core indexes people (users, for user administrators) automatically whenever a user's name,
e-mail or status changes, and matches pages (navigation, admin pages, settings tabs) live.
"""

import re
import unicodedata
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import quote

from pydantic import BaseModel
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from heinzel_api.manifests import Manifest
from heinzel_api.models import User
from heinzel_api.tenants import TenantConfig

CORE = "core"

# --- providers --------------------------------------------------------------------------------

CanView = Callable[[Session, uuid.UUID, list[str]], set[str]]


@dataclass
class Provider:
    module: str
    entity_type: str
    label: str
    icon: str
    can_view: CanView | None = None


_providers: dict[tuple[str, str], Provider] = {}


def register_provider(
    module: str,
    entity_type: str,
    *,
    label: str | None = None,
    icon: str | None = None,
    can_view: CanView | None = None,
) -> None:
    """Register (or complete) a provider. can_view receives the entity ids of the hits and
    returns the ones the user may see."""
    current = _providers.get((module, entity_type))
    _providers[(module, entity_type)] = Provider(
        module,
        entity_type,
        label or (current.label if current else entity_type),
        icon or (current.icon if current else "file"),
        can_view or (current.can_view if current else None),
    )


def providers_from_manifests(manifests: dict[str, Manifest]) -> None:
    """Labels and icons from `contributes.search_providers`."""
    for manifest in manifests.values():
        for entry in manifest.contributes.get("search_providers", []):
            if isinstance(entry, str):
                entry = {"type": entry}
            label = entry.get("label") or manifest.name
            register_provider(
                manifest.id,
                entry["type"],
                label=label.get("de") or next(iter(label.values())),
                icon=entry.get("icon")
                or (manifest.navigation.entry.icon if manifest.navigation else None),
            )


def provider(module: str, entity_type: str) -> Provider:
    return _providers.get((module, entity_type)) or Provider(
        module, entity_type, entity_type, "file"
    )


# --- index ------------------------------------------------------------------------------------

_TSV = """
    setweight(to_tsvector('simple', core.f_unaccent(cast(:title as text))), 'A')
    || setweight(to_tsvector('german', core.f_unaccent(cast(:title as text))), 'B')
    || setweight(to_tsvector('simple', core.f_unaccent(cast(:body as text))), 'C')
    || setweight(to_tsvector('german', core.f_unaccent(cast(:body as text))), 'D')
"""

_UPSERT = text(
    f"""
    insert into core.search_document
        (tenant_id, module, entity_type, entity_id, title, body, meta, link, chip, permission,
         tsv, updated_at)
    values (:tenant_id, :module, :entity_type, :entity_id, cast(:title as text),
            cast(:body as text), :meta, :link,
            cast(:chip as jsonb), :permission, {_TSV}, now())
    on conflict (tenant_id, module, entity_type, entity_id) do update set
        title = excluded.title, body = excluded.body, meta = excluded.meta,
        link = excluded.link, chip = excluded.chip, permission = excluded.permission,
        tsv = excluded.tsv, updated_at = now()
    """
)


def _upsert_params(
    tenant_id: uuid.UUID,
    module: str,
    entity_type: str,
    entity_id: str,
    title: str,
    body: str,
    meta: str,
    link: str,
    permission: str | None,
    chip: dict | None,
) -> dict:
    import json

    return {
        "tenant_id": tenant_id,
        "module": module,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "title": title[:300],
        "body": body,
        "meta": meta[:300],
        "link": link,
        "permission": permission,
        "chip": json.dumps(chip) if chip else None,
    }


def index(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    module: str,
    entity_type: str,
    entity_id: str,
    title: str,
    link: str,
    body: str = "",
    meta: str = "",
    permission: str | None = None,
    chip: dict | None = None,
) -> None:
    """Add or update one document. chip: {"label": ..., "tone": "red|amber|blue|neutral"}."""
    session.execute(
        _UPSERT,
        _upsert_params(
            tenant_id, module, entity_type, entity_id, title, body, meta, link, permission, chip
        ),
    )


def remove(
    session: Session,
    tenant_id: uuid.UUID,
    *,
    module: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> None:
    """Remove one document, all of one type, or all of a module (before a reindex)."""
    sql = "delete from core.search_document where tenant_id = :t and module = :m"
    params: dict = {"t": tenant_id, "m": module}
    if entity_type is not None:
        sql += " and entity_type = :e"
        params["e"] = entity_type
    if entity_id is not None:
        sql += " and entity_id = :i"
        params["i"] = str(entity_id)
    session.execute(text(sql), params)


# --- core provider: people --------------------------------------------------------------------

PEOPLE_PERMISSION = "core.users.manage"
_STATUS_CHIP = {
    "invited": {"label": "Eingeladen", "tone": "amber"},
    "deactivated": {"label": "Deaktiviert", "tone": "neutral"},
}


def _person_params(user: User) -> dict:
    return _upsert_params(
        user.tenant_id,
        CORE,
        "person",
        str(user.id),
        user.display_name,
        user.email,
        user.email,
        f"/admin/benutzer?q={quote(user.email)}",
        PEOPLE_PERMISSION,
        _STATUS_CHIP.get(user.status),
    )


register_provider(CORE, "person", label="Personen", icon="users")


def reindex_core(session: Session, tenant_id: uuid.UUID) -> int:
    """Rebuild the core's documents of one tenant (people)."""
    remove(session, tenant_id, module=CORE)
    users = list(session.query(User).filter(User.tenant_id == tenant_id))
    for user in users:
        session.execute(_UPSERT, _person_params(user))
    return len(users)


@event.listens_for(Session, "after_flush")
def _index_changed_users(session: Session, _ctx) -> None:
    """People stay current without every code path having to remember it."""
    changed = [
        obj
        for obj in (*session.new, *session.dirty)
        if isinstance(obj, User)
        and (
            obj in session.new
            or any(
                inspect(obj).attrs[a].history.has_changes()
                for a in ("display_name", "email", "status")
            )
        )
    ]
    if not changed:
        return
    conn: Connection = session.connection()
    for user in changed:
        conn.execute(_UPSERT, _person_params(user))


# --- query ------------------------------------------------------------------------------------


class Chip(BaseModel):
    label: str
    tone: str = "neutral"


class SearchHit(BaseModel):
    id: str
    title: str
    title_hl: list[tuple[int, int]] = []
    meta: str = ""
    snippet: str | None = None
    snippet_hl: list[tuple[int, int]] = []
    link: str
    chip: Chip | None = None


class SearchGroup(BaseModel):
    key: str
    label: str
    icon: str
    count: int
    items: list[SearchHit]


class SearchResult(BaseModel):
    query: str
    total: int
    groups: list[SearchGroup]


def fold(s: str) -> tuple[str, list[int]]:
    """Lowercase without accents, plus the index of each folded char in the original."""
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(s):
        f = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
        f = f.casefold() or ch
        out.append(f)
        idx.extend([i] * len(f))
    return "".join(out), idx


def tokens(q: str) -> list[str]:
    return [t for t in re.findall(r"\w+", fold(q)[0]) if t][:8]


def highlights(s: str, toks: Iterable[str]) -> list[tuple[int, int]]:
    """Ranges in s where a word starts with one of the tokens (accent- and case-insensitive)."""
    folded, idx = fold(s)
    ranges: list[tuple[int, int]] = []
    for tok in toks:
        for m in re.finditer(r"(?<!\w)" + re.escape(tok), folded):
            ranges.append((idx[m.start()], idx[m.end() - 1] + 1))
    ranges.sort()
    merged: list[tuple[int, int]] = []
    for a, b in ranges:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def _snippet(body: str, toks: list[str], width: int = 110) -> tuple[str, list[tuple[int, int]]]:
    hl = highlights(body, toks)
    if not hl:
        return "", []
    start = max(0, hl[0][0] - 30)
    if start:
        space = body.find(" ", start)
        start = space + 1 if 0 <= space < hl[0][0] else start
    text_ = body[start : start + width].replace("\n", " ")
    prefix = "… " if start else ""
    suffix = " …" if start + width < len(body) else ""
    shift = len(prefix) - start
    ranges = [(a + shift, min(b + shift, len(prefix) + len(text_))) for a, b in hl]
    ranges = [(a, b) for a, b in ranges if len(prefix) <= a < len(prefix) + len(text_)]
    return prefix + text_ + suffix, ranges


@dataclass
class Page:
    title: str
    path: str
    meta: str
    keywords: str = ""


@dataclass
class _Group:
    key: str
    label: str
    icon: str
    best: float = 0.0
    hits: list[SearchHit] = field(default_factory=list)


def searchable_modules(tenant: TenantConfig, manifests: dict[str, Manifest]) -> list[str]:
    mods = [CORE]
    for install in tenant.modules:
        manifest = manifests.get(install.key)
        if not install.enabled or manifest is None:
            continue
        settings = {**manifest.settings_defaults(), **install.settings}
        if settings.get("search_enabled", True) is False:
            continue
        mods.append(install.key)
    return mods


def run(
    session: Session,
    *,
    tenant: TenantConfig,
    manifests: dict[str, Manifest],
    user_id: uuid.UUID,
    permissions: Iterable[str],
    q: str,
    pages: Iterable[Page] = (),
    group: str | None = None,
    per_group: int = 6,
) -> SearchResult:
    """The one search pipeline (dialog, GET /search, MCP tool)."""
    q = q.strip()[:200]
    toks = tokens(q)
    if not toks or len(q) < 2:
        return SearchResult(query=q, total=0, groups=[])
    groups: dict[str, _Group] = {}

    # Pages: matched live against what the user can open (title and keywords, not the
    # section, so "Einstellungen" does not list every settings tab). Title matches first.
    page_hits: list[tuple[int, SearchHit]] = []
    for p in pages:
        hl = highlights(p.title, toks)
        hay = fold(f"{p.title} {p.keywords}")[0]
        if all(re.search(r"(?<!\w)" + re.escape(t), hay) for t in toks):
            hit = SearchHit(id=p.path, title=p.title, title_hl=hl, meta=p.meta, link=p.path)
            page_hits.append((0 if hl else 1, hit))
    if page_hits:
        page_hits.sort(key=lambda x: x[0])
        groups["pages"] = _Group(
            "pages", "Seiten", "compass", best=1.0, hits=[h for _, h in page_hits]
        )

    prefix = " & ".join(f"{t}:*" for t in toks)
    rows = session.execute(
        text(
            """
            with q as (
                select to_tsquery('simple', :prefix)
                       || plainto_tsquery('german', core.f_unaccent(cast(:q as text))) as query
            )
            select module, entity_type, entity_id, title, body, meta, link, chip,
                   ts_rank(tsv, q.query) as rank
            from core.search_document, q
            where tsv @@ q.query
              and module = any(:modules)
              and (permission is null or permission = any(:perms))
            order by rank desc, title
            limit 300
            """
        ),
        {
            "prefix": prefix,
            "q": q,
            "modules": searchable_modules(tenant, manifests),
            "perms": list(permissions),
        },
    ).all()

    by_provider: dict[tuple[str, str], list] = {}
    for row in rows:
        by_provider.setdefault((row.module, row.entity_type), []).append(row)
    for (module, etype), prows in by_provider.items():
        prov = provider(module, etype)
        if prov.can_view is not None:
            allowed = prov.can_view(session, user_id, [r.entity_id for r in prows])
            prows = [r for r in prows if r.entity_id in allowed]
        if not prows:
            continue
        key = f"{module}.{etype}"
        g = groups.setdefault(key, _Group(key, prov.label, prov.icon))
        g.best = max(g.best, float(prows[0].rank))
        for r in prows:
            snippet, snippet_hl = (None, [])
            title_hl = highlights(r.title, toks)
            if r.body and len(title_hl) < len(toks):
                snippet, snippet_hl = _snippet(r.body, toks)
                snippet = snippet or None
            g.hits.append(
                SearchHit(
                    id=r.entity_id,
                    title=r.title,
                    title_hl=title_hl,
                    meta=r.meta,
                    snippet=snippet,
                    snippet_hl=snippet_hl,
                    link=r.link,
                    chip=Chip(**r.chip) if r.chip else None,
                )
            )

    ordered = sorted(groups.values(), key=lambda g: -g.best)
    total = sum(len(g.hits) for g in ordered)
    out = []
    for g in ordered:
        if group and g.key != group:
            continue
        limit = 50 if group else per_group
        out.append(
            SearchGroup(
                key=g.key, label=g.label, icon=g.icon, count=len(g.hits), items=g.hits[:limit]
            )
        )
    return SearchResult(query=q, total=total, groups=out)
