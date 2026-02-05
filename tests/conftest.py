import pytest
import httpx

BASE_URLS = {
    "claude-proxy": "http://localhost:8100",
    "chatgpt-proxy": "http://localhost:8101",
    "grok-proxy": "http://localhost:8102",
    "gemini-proxy": "http://localhost:8103",
    "deepseek-proxy": "http://localhost:8105",
    "claude-code": "http://localhost:8104",
    "ai-router": "http://localhost:8110",
}


@pytest.fixture
def client():
    return httpx.Client(timeout=30.0)


@pytest.fixture
def base_urls():
    return BASE_URLS
