import pytest
from _flows import enrol

pytestmark = pytest.mark.usefixtures("seeded")


def test_defaults_options_and_locks(api, make_user):
    enrol(api, make_user())
    p = api.get("/api/v1/me/preferences").json()
    assert p["values"] == {}
    assert p["effective"]["timezone"] == "Europe/Zurich"
    assert p["locked"] == ["timezone"]  # "currency" is locked too, but not a personal setting
    assert "24h" in p["options"]["time_format"] and p["options"]["language"] == ["de-CH"]


def test_set_reset_and_shell(api, make_user):
    enrol(api, make_user())
    r = api.put(
        "/api/v1/me/preferences",
        json={"localization": {"time_format": "12h", "date_format": "yyyy-MM-dd"}},
    )
    assert r.status_code == 200
    assert r.json()["values"] == {"time_format": "12h", "date_format": "yyyy-MM-dd"}
    assert api.get("/api/v1/shell").json()["user"]["localization"]["time_format"] == "12h"
    assert api.get("/api/v1/me").json()["localization"]["date_format"] == "yyyy-MM-dd"

    r = api.put("/api/v1/me/preferences", json={"localization": {"time_format": None}})
    assert r.json()["values"] == {}
    assert r.json()["effective"]["time_format"] == "24h"


def test_locked_and_invalid_values_are_refused(api, make_user):
    enrol(api, make_user())
    locked = api.put("/api/v1/me/preferences", json={"localization": {"timezone": "UTC"}})
    assert locked.status_code == 422
    bad = api.put("/api/v1/me/preferences", json={"localization": {"time_format": "36h"}})
    assert bad.status_code == 422
    unknown = api.put("/api/v1/me/preferences", json={"localization": {"colour": "red"}})
    assert unknown.status_code == 422
