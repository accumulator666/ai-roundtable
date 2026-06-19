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
    # 1. Capture baseline count of model_call events BEFORE the POST.
    r_before = httpx.get(
        f"{HOLDING}/api/activity",
        params={"action": "model_call", "limit": 1000},
        timeout=30,
    )
    assert r_before.status_code == 200
    baseline = len(r_before.json()["activity"])

    # 2. Drive one focused roundtable turn through Holding.
    resp = httpx.post(
        f"{HOLDING}/api/execute-task",
        json={
            "title": "Reply with the single word OK.",
            "description": "One word only.",
            "skill": "strategy",
            "participants": [],  # empty -> engine falls back to first participant
        },
        timeout=180,
    )
    assert resp.status_code == 200, f"execute-task failed: {resp.status_code} {resp.text[:200]}"

    # 3. Count again — THIS roundtable must have produced new audit rows.
    r_after = httpx.get(
        f"{HOLDING}/api/activity",
        params={"action": "model_call", "limit": 1000},
        timeout=30,
    )
    assert r_after.status_code == 200
    events = r_after.json()["activity"]
    assert len(events) > baseline, (
        f"No new model_call events written: before={baseline}, after={len(events)}. "
        "Audit writer may be missing or wiring is broken."
    )

    # 4. Verify required fields on a model_call event.
    sample = events[0]  # most recent (API returns DESC order)
    assert sample["action"] == "model_call"
    assert sample["actor_type"] == "model"
    assert "latency_ms" in sample["details"], (
        f"latency_ms missing from details: {sample['details']}"
    )

    # 5. Regression-test usage capture — only assert on success events (avoids flake
    #    when all models are down and only failure rows exist).
    success_events = [e for e in events if e["details"].get("success") is True]
    if success_events:
        for evt in success_events:
            assert "total_tokens" in evt["details"], (
                f"total_tokens missing from successful model_call: {evt['details']}"
            )
