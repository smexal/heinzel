from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/src/heinzel_api/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Runtime settings. Override with HEINZEL_* environment variables or a .env file."""

    # .env in the repository root (shared with the web app), then one in the working directory
    model_config = SettingsConfigDict(
        env_prefix="HEINZEL_", env_file=(REPO_ROOT / ".env", ".env"), extra="ignore"
    )

    env: str = "dev"
    # Runtime connection: the non-owner role heinzel_app, so row level security applies.
    database_url: str = "postgresql+psycopg://heinzel_app:heinzel_app@localhost:5432/heinzel"
    # Migrations and CLI admin tasks: the schema owner.
    migration_database_url: str = "postgresql+psycopg://heinzel:heinzel@localhost:5432/heinzel"
    # Password for heinzel_app when a migration has to create the role (dev only).
    app_db_password: str = "heinzel_app"
    # Encrypts secrets at rest (TOTP seeds). Must be set outside dev.
    secret_key: str = "dev-only-insecure-secret-key-change-me"
    # Dev only: send mail to this SMTP host instead of the one in tenant.json
    # (in the Docker stack Mailpit is "mailpit", not localhost).
    smtp_host_override: str | None = None
    valkey_url: str = "redis://localhost:6379/0"
    tenants_dir: Path = REPO_ROOT / "tenants"
    modules_dir: Path = REPO_ROOT / "modules"

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def secure_cookies(self) -> bool:
        """Cookies only over HTTPS, except for local development and tests."""
        return self.env not in ("dev", "test")

    def check(self) -> None:
        """Refuse to start outside dev with development defaults."""
        if not self.is_dev and self.secret_key.startswith("dev-only"):
            raise RuntimeError("HEINZEL_SECRET_KEY must be set outside dev")


@lru_cache
def get_settings() -> Settings:
    return Settings()
