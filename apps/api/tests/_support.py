"""Shared constants for tests (importable as `_support`)."""

import os

OWNER_URL = os.environ.get(
    "HEINZEL_TEST_MIGRATION_DATABASE_URL",
    "postgresql+psycopg://heinzel:heinzel@localhost:5432/heinzel_test",
)
APP_URL = os.environ.get(
    "HEINZEL_TEST_DATABASE_URL",
    "postgresql+psycopg://heinzel_app:heinzel_app@localhost:5432/heinzel_test",
)

PASSWORD = "correct horse battery staple"
