def test_shell_for_schmelzi(client):
    r = client.get("/api/v1/shell", headers={"host": "localhost:8000"})
    assert r.status_code == 200
    shell = r.json()
    assert shell["tenant"] == "schmelzi"
    assert shell["branding"]["display_name"] == "Stiftung Schmelzi"
    assert shell["branding"]["primary"] == "#3B7084"

    top = shell["navigation"][0]
    assert top["label"] is None
    assert [i["label"] for i in top["items"]] == ["Übersicht", "Mein Eingang", "Aufgaben"]

    # empty areas are hidden, administration is always last
    assert [s["key"] for s in shell["navigation"]] == ["top", "admin"]
    assert shell["quick_actions"][0]["label"] == "Aufgabe erfassen"


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
