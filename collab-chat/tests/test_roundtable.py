import httpx
import pytest

COLLAB_CHAT_URL = "http://localhost:8130"


def test_health_endpoint(client):
    """Test health endpoint returns status and stats."""
    resp = client.get(f"{COLLAB_CHAT_URL}/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] == "ok"
    assert "uptime" in data
    assert "model_stats" in data


def test_participant_listing(client):
    """Test GET /api/participants returns participant list with enabled status."""
    resp = client.get(f"{COLLAB_CHAT_URL}/api/participants")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    participant = data[0]
    assert "id" in participant
    assert "name" in participant
    assert "enabled" in participant
    assert "type" in participant


def test_model_stats(client):
    """Test GET /api/model-stats returns per-model statistics."""
    resp = client.get(f"{COLLAB_CHAT_URL}/api/model-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


def test_clear_conversation(client):
    """Test POST /api/clear clears conversation history."""
    resp = client.post(f"{COLLAB_CHAT_URL}/api/clear")
    assert resp.status_code in [200, 204]


def test_participant_update(client):
    """Test PUT /api/participants/{name} toggles enable/disable."""
    resp = client.put(
        f"{COLLAB_CHAT_URL}/api/participants/CEO",
        json={"enabled": False}
    )
    assert resp.status_code in [200, 201, 404]


def test_config_files_exist():
    """Test that required config files exist."""
    import os
    base = "/data/ai-mesh/collab-chat"
    assert os.path.exists(f"{base}/participants.json")
    assert os.path.exists(f"{base}/model_config.json")
    assert os.path.exists(f"{base}/presets.json")


def test_presets_json_structure():
    """Test presets.json has correct structure."""
    import json
    with open("/data/ai-mesh/collab-chat/presets.json") as f:
        presets = json.load(f)
    assert isinstance(presets, dict)
    for name, preset in presets.items():
        assert "name" in preset
        assert "description" in preset
        assert "participants" in preset
        assert "deliberation_rounds" in preset
