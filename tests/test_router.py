import httpx

ROUTER_URL = "http://localhost:8110"


def test_router_health(client):
    resp = client.get(f"{ROUTER_URL}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "ai-router"
    assert "backends" in data


def test_router_models(client):
    resp = client.get(f"{ROUTER_URL}/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert len(data["data"]) >= 5


def test_router_all_backends_registered(client):
    resp = client.get(f"{ROUTER_URL}/health")
    data = resp.json()
    expected = ["claude-proxy", "chatgpt-proxy", "grok-proxy", "gemini-proxy", "deepseek-proxy", "ollama", "claude-code"]
    for backend in expected:
        assert backend in data["backends"], f"Missing backend: {backend}"


def test_chat_completion_explicit_model(client):
    """Test routing to a specific model (Grok since it has working credits)."""
    resp = client.post(f"{ROUTER_URL}/v1/chat/completions", json={
        "model": "grok-3-mini",
        "messages": [{"role": "user", "content": "Reply with just the word: pong"}],
        "max_tokens": 10,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "choices" in data
    assert len(data["choices"]) > 0


def test_multi_completion(client):
    """Test fan-out to multiple models."""
    resp = client.post(f"{ROUTER_URL}/v1/chat/multi", json={
        "models": ["claude-haiku-4-5", "grok-3-mini"],
        "messages": [{"role": "user", "content": "Reply with just: ok"}],
        "max_tokens": 10,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert len(data["results"]) == 2
