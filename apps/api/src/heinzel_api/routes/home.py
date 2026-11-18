"""Übersicht: widgets that modules contribute (contributes.dashboard_widgets)."""

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from heinzel_api import localization, modules
from heinzel_api.db import tenant_session
from heinzel_api.deps import PrincipalDep, TenantDep

router = APIRouter(prefix="/api/v1", tags=["home"])
log = logging.getLogger(__name__)


class Home(BaseModel):
    widgets: list[modules.Widget]


@router.get("/home", response_model=Home)
def get_home(request: Request, p: PrincipalDep, tenant: TenantDep) -> Home:
    """Widgets of active modules, in the order of the tenant's module list. A module switches
    one off with the setting widget_enabled; a widget returns None when it has nothing for
    this user (e.g. missing permission). A failing widget is left out, never the page."""
    hosts: dict[str, modules.ModuleHost] = request.app.state.modules
    loc = localization.effective(tenant.config, p.preferences)
    widgets: list[modules.Widget] = []
    for inst in tenant.config.modules:
        host = hosts.get(inst.key)
        if not inst.enabled or host is None or not host.widgets:
            continue
        settings = modules.settings_for(tenant.config, host.manifest)
        if settings.get("widget_enabled", True) is False:
            continue
        for key, fn in host.widgets.items():
            try:
                with tenant_session(request.app.state.db, tenant.id) as s:
                    w = fn(
                        modules.WidgetContext(
                            session=s,
                            tenant_id=tenant.id,
                            tenant=tenant.config,
                            user_id=p.user_id,
                            permissions=p.permissions,
                            localization=loc,
                            settings=settings,
                        )
                    )
            except Exception:
                log.exception("widget %s.%s failed", inst.key, key)
                continue
            if w is not None:
                widgets.append(w)
    return Home(widgets=widgets)
