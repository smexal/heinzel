"""Module manifests (heinzel.module.yaml): loading and validation of the module contract."""

import json
from pathlib import Path
from typing import Literal

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

LocalizedText = dict[str, str]

MODULE_ID = r"^[a-z][a-z0-9_-]{1,40}$"
PERMISSION_ID = r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_]*){2}$|^[a-z][a-z0-9_-]*\.[a-z][a-z0-9_]*$"
MAX_CHILDREN = 8


class Permission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=PERMISSION_ID)
    label: LocalizedText
    default_roles: list[str] = []


class NavEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: LocalizedText
    path: str = Field(pattern=r"^/")
    icon: str | None = None
    permission: str


class Navigation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_area: str | None = None  # None = top section next to Übersicht and Mein Eingang
    entry: NavEntry
    children: list[NavEntry] = Field(default_factory=list, max_length=MAX_CHILDREN)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=MODULE_ID)
    name: LocalizedText
    description: LocalizedText = {}
    version: str
    core_api: str
    runtime: Literal["in-process"] = "in-process"
    permissions: list[Permission] = []
    uses_core: list[str] = []
    navigation: Navigation | None = None
    contributes: dict = {}
    events: dict[str, list[str]] = {}
    settings_schema: str | None = None
    mcp: dict = {}

    # Loaded from settings_schema (JSON Schema 2020-12) next to the manifest.
    _settings_schema: dict | None = PrivateAttr(default=None)

    @property
    def settings_json_schema(self) -> dict | None:
        return self._settings_schema

    def settings_defaults(self) -> dict:
        props = (self._settings_schema or {}).get("properties", {})
        return {k: v["default"] for k, v in props.items() if "default" in v}

    def validate_settings(self, values: dict) -> list[str]:
        """Errors (empty when valid) for module settings against the module's schema."""
        if self._settings_schema is None:
            return [] if not values else ["module has no settings"]
        validator = Draft202012Validator(self._settings_schema)
        return [
            f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
            for e in validator.iter_errors(values)
        ]

    @model_validator(mode="after")
    def _check_contract(self) -> "Manifest":
        declared = {p.id for p in self.permissions}
        for p in self.permissions:
            if not p.id.startswith(f"{self.id}."):
                raise ValueError(f"permission '{p.id}' must start with '{self.id}.'")
        if self.navigation:
            for entry in [self.navigation.entry, *self.navigation.children]:
                if entry.permission not in declared:
                    raise ValueError(
                        f"navigation '{entry.path}' uses undeclared permission '{entry.permission}'"
                    )
        for tool in self.mcp.get("tools", []):
            if tool.get("permission") not in declared:
                raise ValueError(f"MCP tool '{tool.get('name')}' uses an undeclared permission")
        return self


def load_manifest(path: Path) -> Manifest:
    with path.open(encoding="utf-8") as f:
        manifest = Manifest.model_validate(yaml.safe_load(f))
    if manifest.settings_schema:
        schema_path = path.parent / manifest.settings_schema
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        manifest._settings_schema = schema
    return manifest


def load_manifests(modules_dir: Path) -> dict[str, Manifest]:
    """Load every modules/<id>/heinzel.module.yaml. The folder name must equal the module id."""
    manifests: dict[str, Manifest] = {}
    for path in sorted(modules_dir.glob("*/heinzel.module.yaml")):
        manifest = load_manifest(path)
        if manifest.id != path.parent.name:
            raise ValueError(
                f"{path}: id '{manifest.id}' does not match folder '{path.parent.name}'"
            )
        if manifest.id in manifests:
            raise ValueError(f"duplicate module id '{manifest.id}'")
        manifests[manifest.id] = manifest
    return manifests
