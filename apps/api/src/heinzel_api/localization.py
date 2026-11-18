"""Personal language and regional settings.

Resolution: user setting → tenant default (tenant.json localization.defaults) → platform
default. A setting the tenant locks applies to everyone and cannot be stored per user.
Clients format with these values; the API itself returns ISO 8601 (UTC) and raw numbers.
"""

from functools import lru_cache
from typing import Any
from zoneinfo import available_timezones

from heinzel_api.tenants import TenantConfig

KEYS = ("language", "timezone", "date_format", "time_format", "first_day_of_week", "number_format")

PLATFORM_DEFAULTS: dict[str, str] = {
    "language": "de-CH",
    "timezone": "Europe/Zurich",
    "date_format": "dd.MM.yyyy",
    "time_format": "24h",
    "first_day_of_week": "monday",
    "number_format": "1'234.50",
}

LANGUAGE_LABELS = {"de-CH": "Deutsch (Schweiz)", "fr-CH": "Français (Suisse)", "en": "English"}

FIXED_OPTIONS: dict[str, list[str]] = {
    "date_format": ["dd.MM.yyyy", "yyyy-MM-dd", "dd/MM/yyyy", "MM/dd/yyyy"],
    "time_format": ["24h", "12h"],
    "first_day_of_week": ["monday", "sunday", "saturday"],
    "number_format": ["1'234.50", "1.234,50", "1,234.50", "1 234,50"],
}


@lru_cache
def _timezones() -> list[str]:
    return sorted(tz for tz in available_timezones() if "/" in tz and not tz.startswith("Etc/"))


def tenant_localization(tenant: TenantConfig) -> dict[str, Any]:
    return (tenant.model_extra or {}).get("localization") or {}


def defaults(tenant: TenantConfig) -> dict[str, str]:
    loc = tenant_localization(tenant)
    return {**PLATFORM_DEFAULTS, **{k: v for k, v in loc.get("defaults", {}).items() if k in KEYS}}


def locked(tenant: TenantConfig) -> list[str]:
    return [k for k in tenant_localization(tenant).get("locked", []) if k in KEYS]


def options(tenant: TenantConfig) -> dict[str, list[str]]:
    languages = tenant_localization(tenant).get("languages") or [PLATFORM_DEFAULTS["language"]]
    return {"language": list(languages), "timezone": _timezones(), **FIXED_OPTIONS}


def user_values(preferences: dict[str, Any]) -> dict[str, str]:
    stored = preferences.get("localization") or {}
    return {k: v for k, v in stored.items() if k in KEYS and v}


def effective(tenant: TenantConfig, preferences: dict[str, Any]) -> dict[str, str]:
    lock = set(locked(tenant))
    own = {k: v for k, v in user_values(preferences).items() if k not in lock}
    allowed = options(tenant)
    # A stored value the tenant no longer offers (e.g. a removed language) falls back.
    own = {k: v for k, v in own.items() if v in allowed[k]}
    return {**defaults(tenant), **own}


def validate(tenant: TenantConfig, values: dict[str, str | None]) -> dict[str, str]:
    """Return the values to store (None = follow the tenant default). Raises ValueError."""
    lock = set(locked(tenant))
    allowed = options(tenant)
    out: dict[str, str] = {}
    for key, value in values.items():
        if key not in KEYS:
            raise ValueError(f"unknown setting '{key}'")
        if value is None:
            continue
        if key in lock:
            raise ValueError(f"'{key}' is set by the administration")
        if value not in allowed[key]:
            raise ValueError(f"'{value}' is not an option for '{key}'")
        out[key] = value
    return out
