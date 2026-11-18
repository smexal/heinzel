"""Login helpers shared by API tests."""

import re
import time

import pyotp
from _support import PASSWORD


def login(api, email, password=PASSWORD):
    return api.post("/api/v1/auth/login", json={"email": email, "password": password})


def enrol(api, email, password=PASSWORD) -> pyotp.TOTP:
    """First login of a user without MFA: password, enrolment, confirm."""
    r = login(api, email, password)
    assert r.status_code == 200 and r.json() == {"next": "mfa_setup"}, r.text
    setup = api.post("/api/v1/auth/mfa/setup").json()
    totp = pyotp.TOTP(setup["secret"])
    r = api.post("/api/v1/auth/mfa/confirm", json={"code": totp.now()})
    assert r.status_code == 200, r.text
    return totp


def relogin(api, email, totp: pyotp.TOTP, password=PASSWORD, ahead: int = 30):
    """Login of an enrolled user; uses a later time step so codes are never replayed."""
    api.cookies.clear()
    assert login(api, email, password).json() == {"next": "totp"}
    r = api.post("/api/v1/auth/totp", json={"code": totp.at(time.time() + ahead)})
    assert r.status_code == 200, r.text


def link_token(text: str) -> str:
    m = re.search(r"/konto/([A-Za-z0-9_-]+)", text)
    assert m, text
    return m.group(1)
