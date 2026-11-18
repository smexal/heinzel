"""Einstellungen: tenant settings in the database, sections, versions, logos, step-up."""

import pytest
from _flows import enrol, step_up

pytestmark = pytest.mark.usefixtures("seeded")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'


@pytest.fixture
def admin(api, make_user):
    return enrol(api, make_user(roles=("admin",)))


def _get(api):
    r = api.get("/api/v1/admin/settings")
    assert r.status_code == 200, r.text
    return r.json()


def _put(api, section, values, version, secure=False):
    path = f"/api/v1/admin/settings/{'secure/' if secure else ''}{section}"
    return api.put(path, json={"version": version, "values": values})


def test_staff_cannot_read_settings(api, make_user):
    enrol(api, make_user())
    assert api.get("/api/v1/admin/settings").status_code == 403


def test_branding_change_reaches_shell_and_is_audited(api, admin):
    s = _get(api)
    b = s["sections"]["branding"]
    values = {
        "colors": {"primary": "#224466", "accent": b["colors"]["accent"]},
        "theme_default": "dark",
        "powered_by": True,
    }
    r = _put(api, "branding", values, s["version"])
    assert r.status_code == 200 and r.json()["changed"]
    shell = api.get("/api/v1/shell").json()
    assert shell["branding"]["primary"] == "#224466"
    assert shell["branding"]["theme_default"] == "dark"
    ev = api.get("/api/v1/admin/audit", params={"q": "settings.changed"}).json()["events"][0]
    assert ev["target_id"] == "branding"
    assert ev["data"]["after"]["colors"]["primary"] == "#224466"
    # restore
    s2 = _get(api)
    _put(
        api, "branding", {**values, "colors": b["colors"], "theme_default": "system"}, s2["version"]
    )


def test_stale_version_is_rejected(api, admin):
    s = _get(api)
    g = s["sections"]["general"]
    assert _put(api, "general", g, s["version"]).status_code == 200  # no change, no bump
    _put(api, "general", {**g, "short_name": "Schmelzi X"}, s["version"])
    r = _put(api, "general", g, s["version"])
    assert r.status_code == 409 and r.json()["detail"] == "version_conflict"
    _put(api, "general", g, _get(api)["version"])


def test_localization_validation_and_locks(api, admin):
    s = _get(api)
    loc = s["sections"]["localization"]
    bad = {**loc, "defaults": {**loc["defaults"], "language": "fr-CH"}}
    assert (
        _put(api, "localization", bad, s["version"]).json()["detail"]
        == "default_language_not_offered"
    )
    ok = {**loc, "locked": ["timezone", "currency", "date_format"]}
    assert _put(api, "localization", ok, s["version"]).status_code == 200
    prefs = api.get("/api/v1/me/preferences").json()
    assert "date_format" in prefs["locked"]
    _put(api, "localization", loc, _get(api)["version"])


def test_identity_and_email_need_step_up(api, admin):
    s = _get(api)
    ident = s["sections"]["identity"]
    r = _put(api, "identity", ident, s["version"], secure=True)
    assert r.status_code == 403 and r.json()["detail"] == "step_up_required"
    # the plain route refuses security sections
    assert _put(api, "identity", ident, s["version"]).status_code == 404
    step_up(api, admin)
    no_login = {**ident, "local": {**ident["local"], "enabled": False}}
    r = _put(api, "identity", no_login, s["version"], secure=True)
    assert r.status_code == 409 and r.json()["detail"] == "no_login_left"
    stricter = {**ident, "local": {**ident["local"], "password_min_length": 14}}
    assert _put(api, "identity", stricter, s["version"], secure=True).status_code == 200
    _put(api, "identity", ident, _get(api)["version"], secure=True)


def test_smtp_password_is_write_only(api, admin):
    step_up(api, admin)
    s = _get(api)
    email = s["sections"]["email"]
    assert email["smtp"]["password_set"] is False
    smtp = {k: v for k, v in email["smtp"].items() if k != "password_set"}
    values = {**email, "smtp": {**smtp, "username": "mailer", "password": "geheim"}}
    assert _put(api, "email", values, s["version"], secure=True).status_code == 200
    after = _get(api)
    assert after["sections"]["email"]["smtp"]["password_set"] is True
    assert "geheim" not in api.get("/api/v1/admin/settings").text
    ev = api.get("/api/v1/admin/audit", params={"q": "settings.changed"}).json()["events"][0]
    assert "geheim" not in str(ev["data"])
    # None keeps, "" removes
    keep = {**values, "smtp": {**values["smtp"], "password": None}}
    _put(api, "email", keep, after["version"], secure=True)
    assert _get(api)["sections"]["email"]["smtp"]["password_set"] is True
    clear = {**values, "smtp": {**smtp, "password": ""}}
    _put(api, "email", clear, _get(api)["version"], secure=True)
    assert _get(api)["sections"]["email"]["smtp"]["password_set"] is False


def test_test_mail(api, admin):
    r = api.post("/api/v1/admin/settings/email/test")
    assert r.status_code == 200 and r.json()["sent"]
    assert api.app.state.mailer.sent[-1].subject.startswith("Test-E-Mail")


def test_logo_upload_replace_and_serve(api, admin):
    r = api.put(
        "/api/v1/admin/settings/branding/logos/mark",
        content=PNG,
        headers={"content-type": "image/png"},
    )
    assert r.status_code == 200
    name = r.json()["name"]
    assert name.startswith("logo-mark-") and name.endswith(".png")
    shell = api.get("/api/v1/shell").json()
    assert shell["branding"]["logo_mark"].endswith(name)
    img = api.get(shell["branding"]["logo_mark"])
    assert img.status_code == 200 and img.content == PNG

    r2 = api.put("/api/v1/admin/settings/branding/logos/mark", content=SVG)
    assert r2.json()["name"].endswith(".svg")
    assert api.get(f"/api/v1/tenants/schmelzi/assets/{name}").status_code == 404  # old removed

    bad = api.put("/api/v1/admin/settings/branding/logos/mark", content=b"<script>x</script>")
    assert bad.status_code == 415
    assert api.delete("/api/v1/admin/settings/branding/logos/light").status_code == 409
    assert api.delete("/api/v1/admin/settings/branding/logos/mark").status_code == 200
    assert api.get("/api/v1/shell").json()["branding"]["logo_mark"] is None
