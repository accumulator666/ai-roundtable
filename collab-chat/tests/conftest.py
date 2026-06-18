import pytest
import httpx


@pytest.fixture
def client():
    return httpx.Client(timeout=30.0)
