"""
Holding Company Board Room — port 8130
CEO, CFO, COO make strategic decisions and allocate capital across subsidiaries.

Fortune 500 workflow:
  POST /api/pitch — CEO pitches idea → AI generates project outline with task assignments
  GET  /api/projects — List all projects
  GET  /api/projects/{id} — Project detail with per-company task breakdown
  POST /api/projects/{id}/execute — Kick off parallel execution across companies
  POST /api/projects/{id}/integrate — Combine all results into final deliverable
"""
import sys
sys.path.insert(0, "/app")

import asyncio
import logging
from shared.base_app import create_company_app

logger = logging.getLogger("holding")

# Lazy-init orchestrator (created on first use so imports resolve after app starts)
_orchestrator = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        from shared.orchestrator import ProjectOrchestrator
        _orchestrator = ProjectOrchestrator()
    return _orchestrator


def add_holding_routes(app):
    """Board-level endpoints: capital allocation, P&L rollup, directives, and project orchestration."""

    # ----------------------------------------------------------
    # Existing endpoints
    # ----------------------------------------------------------

    @app.get("/api/rollup")
    async def get_rollup():
        """P&L rollup across all subsidiaries."""
        try:
            from shared.db import get_holding_rollup
            return {"companies": await get_holding_rollup()}
        except Exception as e:
            return {"error": str(e)}

    @app.get("/api/transfers")
    async def get_transfers():
        """Pending capital transfer requests."""
        try:
            from shared.db import get_pending_transfers
            return {"transfers": await get_pending_transfers()}
        except Exception as e:
            return {"error": str(e)}

    @app.post("/api/approve-transfer/{transfer_id}")
    async def approve_transfer(transfer_id: str, approved_by: str = "CEO"):
        try:
            from shared.db import approve_transfer as _approve
            from uuid import UUID
            ok = await _approve(UUID(transfer_id), approved_by)
            return {"status": "approved" if ok else "not found or already processed"}
        except Exception as e:
            return {"error": str(e)}

    @app.post("/api/directive")
    async def send_directive(request: dict):
        """CEO sends a strategic directive to a company or all."""
        try:
            from shared.company_comms import strategic_directive
            target = request.get("target", "all")
            await strategic_directive(request.get("directive", ""), target)
            return {"status": f"directive sent to {target}"}
        except Exception as e:
            return {"error": str(e)}

    @app.get("/api/all-companies")
    async def all_companies():
        try:
            from shared.db import get_all_companies
            return {"companies": await get_all_companies()}
        except Exception as e:
            return {"error": str(e)}

    # ----------------------------------------------------------
    # Fortune 500 Project Orchestration
    # ----------------------------------------------------------

    @app.post("/api/pitch")
    async def create_pitch(request: dict):
        """
        CEO pitches a new business idea.
        AI generates a structured project outline with tasks auto-assigned
        to the right specialists across all companies.

        Body: {"pitch": "Build a SaaS tool for ...", "model": "gpt-5.2"}
        """
        pitch = request.get("pitch", "").strip()
        if not pitch:
            return {"error": "pitch is required"}

        model = request.get("model", "gpt-5.2")
        orch = get_orchestrator()

        try:
            project = await orch.pitch_to_project(pitch, model=model)
        except Exception as e:
            logger.error(f"Pitch failed: {e}")
            return {"error": str(e)}

        # Broadcast to all companies that a new project was created
        try:
            from shared.company_comms import broadcast
            await broadcast({
                "type": "new_project",
                "project_id": project["id"],
                "name": project["outline"].get("project_name", "Unknown"),
                "task_count": len(project["tasks"]),
            }, sender_code="holding")
        except Exception:
            pass

        return {
            "project_id": project["id"],
            "name": project["outline"].get("project_name", "Unknown"),
            "summary": project["outline"].get("summary", ""),
            "phases": len(project["outline"].get("phases", [])),
            "tasks": len(project["tasks"]),
            "task_breakdown": orch.get_task_summary(project["id"]),
        }

    @app.get("/api/projects")
    async def list_projects():
        """List all projects with status summary."""
        orch = get_orchestrator()
        # Try DB first, fall back to in-memory
        try:
            from shared.db import list_projects as db_list
            return {"projects": await db_list()}
        except Exception:
            return {"projects": orch.list_projects()}

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str):
        """Get project detail with per-company task breakdown."""
        orch = get_orchestrator()
        project = orch.get_project(project_id)
        if not project:
            # Try loading from DB
            try:
                from shared.db import get_project as db_get
                project = await db_get(project_id)
            except Exception:
                pass
        if not project:
            return {"error": "Project not found"}

        return {
            "id": project["id"],
            "pitch": project.get("pitch", ""),
            "outline": project.get("outline", {}),
            "status": project.get("status", "unknown"),
            "task_summary": orch.get_task_summary(project_id) if orch.get_project(project_id) else {},
            "tasks": project.get("tasks", []),
            "synthesis": project.get("synthesis"),
        }

    @app.post("/api/projects/{project_id}/execute")
    async def execute_project(project_id: str):
        """
        Kick off parallel execution — sends each task to the right company.
        Each company runs a focused roundtable with the assigned specialists.
        Returns immediately; progress streamed via WebSocket.
        """
        orch = get_orchestrator()
        project = orch.get_project(project_id)
        if not project:
            return {"error": "Project not found (must pitch first)"}
        if project["status"] not in ("planned", "executed"):
            return {"error": f"Project status is '{project['status']}', expected 'planned'"}

        # Import ws_broadcast from base_app context (injected via closure)
        from shared.base_app import create_company_app

        async def on_progress(event):
            """Forward execution progress to connected WebSocket clients."""
            try:
                # We access the broadcast function through the app's state
                if hasattr(app, '_ws_broadcast'):
                    await app._ws_broadcast({
                        "type": "project_progress",
                        "project_id": project_id,
                        **event,
                    })
            except Exception:
                pass

        # Run execution in background so API returns immediately
        async def _run():
            try:
                await orch.execute(project_id, on_progress=on_progress)
                if hasattr(app, '_ws_broadcast'):
                    await app._ws_broadcast({
                        "type": "project_execution_complete",
                        "project_id": project_id,
                        "summary": orch.get_task_summary(project_id),
                    })
            except Exception as e:
                logger.error(f"Execution failed: {e}")

        asyncio.create_task(_run())

        return {
            "status": "executing",
            "project_id": project_id,
            "task_count": len(project["tasks"]),
            "companies_involved": list({t["assigned_company"] for t in project["tasks"]}),
        }

    @app.post("/api/projects/{project_id}/integrate")
    async def integrate_project(project_id: str, request: dict = {}):
        """
        Reconvene the team — combine all completed task results
        into one cohesive deliverable.
        """
        orch = get_orchestrator()
        project = orch.get_project(project_id)
        if not project:
            return {"error": "Project not found"}

        model = request.get("model", "gpt-5.2") if isinstance(request, dict) else "gpt-5.2"

        try:
            result = await orch.integrate(project_id, model=model)
        except Exception as e:
            return {"error": str(e)}

        if "error" in result:
            return result

        # Broadcast completion
        try:
            from shared.company_comms import broadcast
            await broadcast({
                "type": "project_completed",
                "project_id": project_id,
                "name": result["outline"].get("project_name", "Unknown"),
            }, sender_code="holding")
        except Exception:
            pass

        return {
            "project_id": project_id,
            "status": result["status"],
            "synthesis": result.get("synthesis", ""),
            "task_summary": orch.get_task_summary(project_id),
        }

    @app.get("/api/skills")
    async def list_skills():
        """List all available skills and their routing."""
        from shared.orchestrator import SKILL_ROUTING
        return {"skills": SKILL_ROUTING}


async def holding_startup():
    """Pre-load orchestrator on startup."""
    get_orchestrator()
    logger.info("Project orchestrator initialized")


app = create_company_app(extra_startup=holding_startup, extra_routes=add_holding_routes)
