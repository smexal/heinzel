import pytest
from fastapi.testclient import TestClient

from heinzel_api.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c
