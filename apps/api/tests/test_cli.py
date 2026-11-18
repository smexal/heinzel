"""Operator commands."""

from _support import OWNER_URL
from alembic.script import ScriptDirectory

from heinzel_api.cli import main, pending_migrations


def test_pending_migrations_detected(migrated, monkeypatch, capsys):
    assert pending_migrations(OWNER_URL) == []
    monkeypatch.setattr(ScriptDirectory, "get_current_head", lambda self: "9999_future")
    behind = pending_migrations(OWNER_URL)
    assert behind[0][0] == "core" and behind[0][2] == "9999_future" and behind[0][1]
    monkeypatch.setenv("HEINZEL_MIGRATION_DATABASE_URL", OWNER_URL)
    from heinzel_api.config import get_settings

    get_settings.cache_clear()
    try:
        assert main(["verify-audit", "--tenant", "schmelzi"]) == 3
    finally:
        get_settings.cache_clear()
    assert "heinzel migrate" in capsys.readouterr().err
