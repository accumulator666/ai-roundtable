import pytest
import httpx

COLLAB_CHAT_URL = "http://localhost:8130"


@pytest.fixture
def collab_client():
    return httpx.Client(timeout=30.0, base_url=COLLAB_CHAT_URL)


@pytest.fixture
def collab_async_client():
    return httpx.AsyncClient(timeout=30.0, base_url=COLLAB_CHAT_URL)
