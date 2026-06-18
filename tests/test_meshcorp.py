"""
Integration tests for MeshCorp HQ.
Requires: meshcorp-hq container running at localhost:8160
           ai-router running at localhost:8110
"""
import httpx
import pytest

BASE_URL = "http://localhost:8160"


@pytest.fixture
def client():
    return httpx.Client(base_url=BASE_URL, timeout=30.0)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "meshcorp-hq"


def test_list_templates(client):
    r = client.get("/api/templates")
    assert r.status_code == 200
    templates = r.json()["templates"]
    assert len(templates) >= 7
    names = [t["name"] for t in templates]
    assert "Tech Startup" in names
    assert "Hedge Fund" in names
    assert "Law Firm" in names
    assert "Marketing Agency" in names
    assert "Research Lab" in names
    assert "E-Commerce" in names
    assert "Consulting Firm" in names


def test_get_template(client):
    r = client.get("/api/templates/tech-startup")
    assert r.status_code == 200
    t = r.json()
    assert t["id"] == "tech-startup"
    assert len(t["roles"]) >= 5
    # Verify lead exists
    leads = [role for role in t["roles"] if role.get("is_lead")]
    assert len(leads) == 1


def test_template_not_found(client):
    r = client.get("/api/templates/nonexistent")
    assert r.status_code == 404


def test_dashboard(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert "active_projects" in data
    assert "planning_projects" in data
    assert "proposals" in data
    assert "pending_actions" in data
    assert "financials" in data
    assert "total_allocated" in data["financials"]
    assert "total_spent" in data["financials"]


def test_list_projects_empty(client):
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert "projects" in r.json()


def test_list_actions_empty(client):
    r = client.get("/api/actions")
    assert r.status_code == 200
    assert "actions" in r.json()


def test_get_project_not_found(client):
    r = client.get("/api/projects/nonexistent")
    assert r.status_code == 404


def test_create_project(client):
    """Create a project using tech-startup template. Uses cheap model for speed."""
    r = client.post("/api/projects", json={
        "template_id": "tech-startup",
        "description": "Build a simple todo list API with user authentication",
        "model": "deepseek-chat",
    }, timeout=120.0)
    assert r.status_code == 200
    data = r.json()
    assert data["id"]
    assert data["name"]
    assert data["template_id"] == "tech-startup"
    assert data["status"] == "planning"
    assert len(data["team"]) >= 5
    assert len(data["milestones"]) >= 3
    return data["id"]


def test_create_project_bad_template(client):
    r = client.post("/api/projects", json={
        "template_id": "nonexistent",
        "description": "test",
    })
    assert r.status_code == 400
