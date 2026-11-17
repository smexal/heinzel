from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/src/heinzel_api/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Runtime settings. Override with HEINZEL_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="HEINZEL_", env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "postgresql+psycopg://heinzel:heinzel@localhost:5432/heinzel"
    valkey_url: str = "redis://localhost:6379/0"
    tenants_dir: Path = REPO_ROOT / "tenants"
    modules_dir: Path = REPO_ROOT / "modules"


@lru_cache
def get_settings() -> Settings:
    return Settings()
