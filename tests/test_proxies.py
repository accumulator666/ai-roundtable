import httpx
import pytest

PROXIES = [
    ("claude-proxy", "http://localhost:8100"),
    ("chatgpt-proxy", "http://localhost:8101"),
    ("grok-proxy", "http://localhost:8102"),
    ("gemini-proxy", "http://localhost:8103"),
    ("deepseek-proxy", "http://localhost:8105"),
    ("claude-code", "http://localhost:8104"),
]


@pytest.mark.parametrize("name,url", PROXIES)
def test_health(client, name, url):
    resp = client.get(f"{url}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == name


@pytest.mark.parametrize("name,url", PROXIES)
def test_list_models(client, name, url):
    resp = client.get(f"{url}/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert len(data["data"]) > 0
