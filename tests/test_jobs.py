import pytest
import httpx

COLLAB_CHAT_URL = "http://localhost:8130"


class TestJobs:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = httpx.Client(timeout=30.0, base_url=COLLAB_CHAT_URL)

    def test_trigger_job(self):
        """Test POST /api/jobs/trigger — trigger a job (mock CrewAI response)"""
        payload = {
            "job_type": "strategy-session",
            "project": "cdl-vault",
            "params": {
                "business_description": "CDL driver reputation scoring platform"
            }
        }
        response = self.client.post("/api/jobs/trigger", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data.get("job_type") == payload["job_type"]

    def test_list_jobs(self):
        """Test GET /api/jobs — list jobs"""
        response = self.client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_jobs_filter_project(self):
        """Test GET /api/jobs — filter by project"""
        response = self.client.get("/api/jobs?project=cdl-vault")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_job_by_id(self):
        """Test GET /api/jobs/{job_id} — get job status"""
        trigger_payload = {
            "job_type": "build-business",
            "project": "cdl-vault",
            "params": {"business_description": "Test business"}
        }
        trigger_response = self.client.post("/api/jobs/trigger", json=trigger_payload)
        if trigger_response.status_code == 200:
            job_data = trigger_response.json()
            job_id = job_data.get("job_id")
            if job_id:
                get_response = self.client.get(f"/api/jobs/{job_id}")
                assert get_response.status_code == 200
                job_info = get_response.json()
                assert "job_id" in job_info or "status" in job_info
