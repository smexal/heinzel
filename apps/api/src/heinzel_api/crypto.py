"""Secrets at rest and token helpers."""

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _fernet(secret_key: str, purpose: str) -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=f"heinzel:{purpose}".encode()
    ).derive(secret_key.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(secret_key: str, purpose: str, value: str) -> str:
    return _fernet(secret_key, purpose).encrypt(value.encode()).decode()


def decrypt(secret_key: str, purpose: str, token: str) -> str:
    return _fernet(secret_key, purpose).decrypt(token.encode()).decode()


def new_token() -> str:
    """256 bit random token for cookies and links."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
