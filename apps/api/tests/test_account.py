"""Forgotten password, reset links, change password, rate limits."""

import pytest
from _flows import enrol, link_token, login, relogin
from _support import PASSWORD

pytestmark = pytest.mark.usefixtures("seeded")

NEW = "a brand new passphrase 42"


def _mails(api):
    return api.app.state.mailer.sent


def test_forgot_password_sends_link_only_for_active_users(api, make_user):
    email = make_user()
    assert api.post("/api/v1/auth/password/forgot", json={"email": email}).status_code == 202
    r = api.post("/api/v1/auth/password/forgot", json={"email": "nobody@schmelzi.test"})
    assert r.status_code == 202
    assert [m.to for m in _mails(api)] == [email]
    assert "http://localhost/konto/" in _mails(api)[0].text


def test_reset_link_sets_password_once_and_ends_sessions(api, make_user):
    email = make_user()
    totp = enrol(api, email)
    session_cookie = api.cookies.get("heinzel_session")
    api.post("/api/v1/auth/password/forgot", json={"email": email})
    token = link_token(_mails(api)[-1].text)

    info = api.get(f"/api/v1/auth/token/{token}").json()
    assert info["purpose"] == "password_reset" and info["email"] == email

    short = api.post("/api/v1/auth/password/set", json={"token": token, "password": "short"})
    assert short.status_code == 422 and short.json()["detail"] == "password_policy"
    ok = api.post("/api/v1/auth/password/set", json={"token": token, "password": NEW})
    assert ok.status_code == 204
    again = api.post("/api/v1/auth/password/set", json={"token": token, "password": NEW})
    assert again.status_code == 404

    # the old session is gone, the old password too, MFA stays
    api.cookies.set("heinzel_session", session_cookie)
    assert api.get("/api/v1/me").status_code == 401
    api.cookies.clear()
    assert login(api, email, PASSWORD).status_code == 401
    relogin(api, email, totp, password=NEW)


def test_new_reset_link_invalidates_the_previous_one(api, make_user):
    email = make_user()
    api.post("/api/v1/auth/password/forgot", json={"email": email})
    api.post("/api/v1/auth/password/forgot", json={"email": email})
    first, second = (link_token(m.text) for m in _mails(api))
    assert api.get(f"/api/v1/auth/token/{first}").status_code == 404
    assert api.get(f"/api/v1/auth/token/{second}").status_code == 200


def test_change_password_keeps_current_session(api, make_user):
    email = make_user()
    totp = enrol(api, email)
    wrong = api.post(
        "/api/v1/me/password", json={"current_password": "nope nope nope", "new_password": NEW}
    )
    assert wrong.status_code == 403
    r = api.post("/api/v1/me/password", json={"current_password": PASSWORD, "new_password": NEW})
    assert r.status_code == 204
    assert api.get("/api/v1/me").status_code == 200
    relogin(api, email, totp, password=NEW)


def test_forgot_password_is_rate_limited(api):
    codes = [
        api.post("/api/v1/auth/password/forgot", json={"email": "x@schmelzi.test"}).status_code
        for _ in range(6)
    ]
    assert codes == [202] * 5 + [429]


def test_wrong_totp_codes_lock_the_account(api, make_user):
    email = make_user()
    enrol(api, email)
    api.cookies.clear()
    login(api, email)
    for _ in range(4):
        assert api.post("/api/v1/auth/totp", json={"code": "000000"}).status_code == 401
    # fifth failure locks and ends the pending session
    assert api.post("/api/v1/auth/totp", json={"code": "000000"}).status_code == 401
    assert api.post("/api/v1/auth/totp", json={"code": "000000"}).status_code == 401
    api.cookies.clear()
    assert login(api, email).status_code == 401
