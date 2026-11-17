import pytest
from pydantic import ValidationError

from heinzel_api.config import get_settings
from heinzel_api.manifests import Manifest, load_manifests


def test_repo_manifests_are_valid():
    manifests = load_manifests(get_settings().modules_dir)
    assert "aufgaben" in manifests
    aufgaben = manifests["aufgaben"]
    assert aufgaben.navigation is not None
    assert aufgaben.navigation.default_area is None
    assert aufgaben.navigation.children == []


BASE = {
    "id": "demo",
    "name": {"de": "Demo"},
    "version": "0.1.0",
    "core_api": ">=1.0 <2.0",
    "permissions": [{"id": "demo.item.read", "label": {"de": "Lesen"}}],
}


def test_permission_must_be_prefixed_with_module_id():
    data = {**BASE, "permissions": [{"id": "other.item.read", "label": {"de": "x"}}]}
    with pytest.raises(ValidationError):
        Manifest.model_validate(data)


def test_navigation_needs_declared_permission():
    data = {
        **BASE,
        "navigation": {
            "entry": {"label": {"de": "Demo"}, "path": "/demo", "permission": "demo.x.y"}
        },
    }
    with pytest.raises(ValidationError):
        Manifest.model_validate(data)


def test_only_in_process_runtime():
    with pytest.raises(ValidationError):
        Manifest.model_validate({**BASE, "runtime": "container"})
