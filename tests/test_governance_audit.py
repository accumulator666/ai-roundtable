import httpx

HOLDING = "http://localhost:8130"


def test_activity_endpoint_returns_list():
    r = httpx.get(f"{HOLDING}/api/activity", timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["company"] == "holding"
    assert "activity" in body
    assert isinstance(body["activity"], list)


def test_model_call_is_audited():
    # Drive one focused roundtable turn through Holding, then assert it was logged.
    httpx.post(
        f"{HOLDING}/api/execute-task",
        json={"title": "Reply with the single word OK.",
              "description": "One word only.",
              "skill": "strategy",
              "participants": []},   # empty -> engine falls back to first participant
        timeout=180,
    )
    r = httpx.get(f"{HOLDING}/api/activity", params={"action": "model_call", "limit": 5}, timeout=30)
    assert r.status_code == 200
    events = r.json()["activity"]
    assert len(events) >= 1, "expected at least one model_call audit event"
    assert events[0]["action"] == "model_call"
    assert events[0]["actor_type"] == "model"
    assert "latency_ms" in events[0]["details"]
