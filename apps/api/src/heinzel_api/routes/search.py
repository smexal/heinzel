"""Global search (the Ctrl K dialog). The pipeline itself is heinzel_api.search.run."""

from fastapi import APIRouter, Query

from heinzel_api import search
from heinzel_api.db import tenant_session
from heinzel_api.deps import DbDep, ManifestsDep, PrincipalDep, TenantDep
from heinzel_api.routes.shell import build_shell

router = APIRouter(prefix="/api/v1", tags=["search"])

SETTINGS_TABS = [
    ("general", "Allgemein", "Name Kurzname Mandant"),
    ("branding", "Branding", "Logo Farben Theme Powered by"),
    ("localization", "Sprache & Region", "Sprache Datum Zeitzone Zahlen Währung"),
    ("navigation", "Navigation", "Bereiche Reihenfolge Seitenleiste"),
    ("identity", "Anmeldung", "Passwort Zwei-Faktor 2FA Sitzung"),
    ("email", "E-Mail", "SMTP Absender Mailserver Testmail"),
]
PROFILE_TABS = [
    ("region", "Sprache & Region", "Sprache Datum Zeitzone"),
    ("appearance", "Darstellung", "Hell Dunkel Modus Theme"),
    ("security", "Sicherheit", "Passwort ändern Zwei-Faktor 2FA"),
]


def pages_for(tenant, manifests, permissions) -> list[search.Page]:
    """Everything the user can open: navigation, admin pages and their tabs, profile."""
    shell = build_shell(tenant, manifests, permissions)
    pages: list[search.Page] = []
    for section in shell.navigation:
        where = section.label or "Navigation"
        for item in section.items:
            pages.append(search.Page(item.label, item.path, where))
            for child in item.children:
                pages.append(search.Page(child.label, child.path, f"{where} · {item.label}"))
    if "core.settings.manage" in permissions:
        for key, label, kw in SETTINGS_TABS:
            pages.append(search.Page(label, f"/admin/einstellungen?tab={key}", "Einstellungen", kw))
    if "core.roles.manage" in permissions:
        pages.append(search.Page("Rollen", "/admin/benutzer?tab=rollen", "Benutzer & Rollen"))
    pages.append(search.Page("Mein Profil", "/profil", "Konto"))
    for key, label, kw in PROFILE_TABS:
        pages.append(search.Page(label, f"/profil?tab={key}", "Mein Profil", kw))
    return pages


@router.get("/search", response_model=search.SearchResult)
def run_search(
    p: PrincipalDep,
    tenant: TenantDep,
    db: DbDep,
    manifests: ManifestsDep,
    q: str = Query("", max_length=200),
    group: str | None = Query(None, max_length=120),
) -> search.SearchResult:
    with tenant_session(db, tenant.id) as s:
        return search.run(
            s,
            tenant=tenant.config,
            manifests=manifests,
            user_id=p.user_id,
            permissions=p.permissions,
            q=q,
            pages=pages_for(tenant.config, manifests, p.permissions),
            group=group,
        )
