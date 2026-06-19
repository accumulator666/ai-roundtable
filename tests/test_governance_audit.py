import httpx

HOLDING = "http://localhost:8130"


def test_activity_endpoint_returns_list():
    r = httpx.get(f"{HOLDING}/api/activity", timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert body["company"] == "holding"
    assert "activity" in body
    assert isinstance(body["activity"], list)
