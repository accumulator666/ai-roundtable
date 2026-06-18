import pytest
import httpx

COLLAB_CHAT_URL = "http://localhost:8130"


class TestTasks:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = httpx.Client(timeout=30.0, base_url=COLLAB_CHAT_URL)

    def test_create_task(self):
        """Test POST /api/tasks — create a task, verify response matches TASK_SCHEMA"""
        payload = {
            "title": "Test Task",
            "description": "A test task for the API",
            "project": "cdl-vault",
            "priority": "high",
            "team": "backend-team",
            "language": "python",
            "depends_on": [],
        }
        response = self.client.post("/api/tasks", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert data["title"] == payload["title"]
        assert data["description"] == payload["description"]
        assert data["project"] == payload["project"]
        assert data["status"] == "backlog"
        assert data["priority"] == payload["priority"]
        assert data["team"] == payload["team"]
        assert data["language"] == payload["language"]
        assert "created_at" in data
        assert "updated_at" in data

    def test_list_tasks(self):
        """Test GET /api/tasks — list tasks, filter by project"""
        response = self.client.get("/api/tasks?project=cdl-vault")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_tasks_filter_status(self):
        """Test GET /api/tasks — filter by status"""
        response = self.client.get("/api/tasks?status=backlog")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_list_tasks_filter_team(self):
        """Test GET /api/tasks — filter by team"""
        response = self.client.get("/api/tasks?team=backend-team")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_update_task_status(self):
        """Test PUT /api/tasks/{task_id} — update status from 'backlog' to 'in_progress'"""
        create_payload = {
            "title": "Status Update Test",
            "description": "Testing status updates",
            "project": "cdl-vault",
            "priority": "medium",
        }
        create_response = self.client.post("/api/tasks", json=create_payload)
        assert create_response.status_code == 200
        task_data = create_response.json()
        task_id = task_data["task_id"]

        update_payload = {"status": "in_progress"}
        update_response = self.client.put(f"/api/tasks/{task_id}", json=update_payload)
        assert update_response.status_code == 200
        updated_data = update_response.json()
        assert updated_data["status"] == "in_progress"

    def test_update_task_with_result(self):
        """Test PUT /api/tasks/{task_id} — update with result when completing"""
        create_payload = {
            "title": "Completion Test",
            "description": "Testing task completion",
            "project": "cdl-vault",
            "priority": "low",
        }
        create_response = self.client.post("/api/tasks", json=create_payload)
        assert create_response.status_code == 200
        task_data = create_response.json()
        task_id = task_data["task_id"]

        update_payload = {
            "status": "done",
            "result": "Completed successfully with all requirements met."
        }
        update_response = self.client.put(f"/api/tasks/{task_id}", json=update_payload)
        assert update_response.status_code == 200
        updated_data = update_response.json()
        assert updated_data["status"] == "done"
        assert updated_data["result"] == update_payload["result"]

    def test_delete_task(self):
        """Test DELETE /api/tasks/{task_id} — remove task"""
        create_payload = {
            "title": "Delete Test",
            "description": "Testing task deletion",
            "project": "cdl-vault",
            "priority": "low",
        }
        create_response = self.client.post("/api/tasks", json=create_payload)
        assert create_response.status_code == 200
        task_data = create_response.json()
        task_id = task_data["task_id"]

        delete_response = self.client.delete(f"/api/tasks/{task_id}")
        assert delete_response.status_code == 200

        get_response = self.client.get(f"/api/tasks/{task_id}")
        assert get_response.status_code == 404

    def test_get_tasks_board(self):
        """Test GET /api/tasks/board — verify kanban grouping"""
        response = self.client.get("/api/tasks/board")
        assert response.status_code == 200
        data = response.json()
        assert "backlog" in data
        assert "assigned" in data
        assert "in_progress" in data
        assert "review" in data
        assert "done" in data
        assert "blocked" in data
        for column in ["backlog", "assigned", "in_progress", "review", "done", "blocked"]:
            assert isinstance(data[column], list)

    def test_dependency_tracking(self):
        """Test dependency tracking — completing task A unblocks task B"""
        task_a_payload = {
            "title": "Task A (dependency)",
            "description": "This task will be completed first",
            "project": "cdl-vault",
            "priority": "high",
        }
        task_a_response = self.client.post("/api/tasks", json=task_a_payload)
        assert task_a_response.status_code == 200
        task_a = task_a_response.json()
        task_a_id = task_a["task_id"]

        task_b_payload = {
            "title": "Task B (dependent)",
            "description": "This task depends on Task A",
            "project": "cdl-vault",
            "priority": "medium",
            "depends_on": [task_a_id],
        }
        task_b_response = self.client.post("/api/tasks", json=task_b_payload)
        assert task_b_response.status_code == 200
        task_b = task_b_response.json()

        assert task_a_id in task_b["blocked_by"]

        self.client.put(f"/api/tasks/{task_a_id}", json={"status": "done"})

        updated_b = self.client.get(f"/api/tasks/{task_b['task_id']}").json()
        assert task_a_id not in updated_b.get("blocked_by", [])
