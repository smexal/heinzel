from heinzel_api.config import get_settings
from heinzel_api.manifests import load_manifests
from heinzel_api.routes.shell import build_shell
from heinzel_api.tenants import load_tenants


def _shell(perms):
    s = get_settings()
    tenant = load_tenants(s.tenants_dir)["schmelzi"]
    return build_shell(tenant, load_manifests(s.modules_dir), perms)


def test_anonymous_shell_has_branding_only():
    shell = _shell(None)
    assert shell.tenant == "schmelzi"
    assert shell.branding.display_name == "Stiftung Schmelzi"
    assert shell.branding.primary == "#3B7084"
    assert shell.navigation == [] and shell.quick_actions == []


def test_staff_sees_modules_but_no_admin():
    shell = _shell({"aufgaben.use"})
    top = shell.navigation[0]
    assert top.label is None
    assert [i.label for i in top.items] == ["Übersicht", "Mein Eingang", "Aufgaben"]
    # empty areas are hidden, no administration without core permissions
    assert [s.key for s in shell.navigation] == ["top"]
    assert shell.quick_actions[0].label == "Aufgabe erfassen"


def test_module_hidden_without_permission():
    shell = _shell(set())
    assert [i.key for i in shell.navigation[0].items] == ["home", "inbox"]
    assert shell.quick_actions == []


def test_admin_items_follow_permissions():
    shell = _shell({"aufgaben.use", "core.audit.read"})
    admin = shell.navigation[-1]
    assert admin.key == "admin"
    assert [i.key for i in admin.items] == ["audit"]


def test_unknown_tenant(client):
    r = client.get("/api/v1/shell", headers={"host": "example.org"})
    assert r.status_code == 404


def test_tenant_asset(client):
    r = client.get("/api/v1/tenants/schmelzi/assets/logo-schmelzi.svg")
    assert r.status_code == 200
    assert "svg" in r.headers["content-type"]


def test_tenant_asset_rejects_traversal(client):
    r = client.get("/api/v1/tenants/schmelzi/assets/..%2Ftenant.json")
    assert r.status_code == 404
