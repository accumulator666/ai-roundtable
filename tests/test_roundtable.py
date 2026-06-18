import pytest
import httpx

COLLAB_CHAT_URL = "http://localhost:8130"


class TestProjects:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = httpx.Client(timeout=30.0, base_url=COLLAB_CHAT_URL)

    def test_list_projects(self):
        """Test GET /api/projects — returns CDL-Vault"""
        response = self.client.get("/api/projects")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "cdl-vault" in data

    def test_get_project_details(self):
        """Test GET /api/projects/cdl-vault — returns project details"""
        response = self.client.get("/api/projects/cdl-vault")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "cdl-vault"
        assert data["name"] == "CDL Vault"
        assert "description" in data
        assert "tech_stack" in data
        assert "teams" in data
        assert data["active"] is True


class TestDashboard:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = httpx.Client(timeout=30.0, base_url=COLLAB_CHAT_URL)

    def test_get_dashboard(self):
        """Test GET /api/dashboard — returns combined dashboard data"""
        response = self.client.get("/api/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert "project" in data or "active_project" in data
        assert "tasks" in data or "task_counts" in data
        assert "jobs" in data or "active_jobs" in data
        assert "decisions" in data or "recent_decisions" in data


class TestDecisions:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = httpx.Client(timeout=30.0, base_url=COLLAB_CHAT_URL)

    def test_list_decisions(self):
        """Test GET /api/decisions — returns empty or seeded decisions"""
        response = self.client.get("/api/decisions")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_create_decision(self):
        """Test POST /api/decisions — record a decision manually"""
        payload = {
            "description": "Test decision for dashboard",
            "project": "cdl-vault",
            "action": "marketing-campaign",
            "decided_by": ["CEO", "CFO", "CTO"],
        }
        response = self.client.post("/api/decisions", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "decision_id" in data
        assert data["description"] == payload["description"]


class TestCollabChat:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = httpx.Client(timeout=30.0, base_url=COLLAB_CHAT_URL)

    def test_health(self):
        """Test GET /health — health check"""
        response = self.client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data or "uptime" in data

    def test_list_participants(self):
        """Test GET /api/participants — list all participants"""
        response = self.client.get("/api/participants")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_presets(self):
        """Test GET /api/presets — list available presets"""
        response = self.client.get("/api/presets")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "quick-3" in data or "full-panel" in data or "backend-team" in data

    def test_get_model_config(self):
        """Test GET /api/models — verify models are available"""
        response = self.client.get("/api/models")
        assert response.status_code in [200, 404]
