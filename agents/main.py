import os
import time
import uuid
import logging
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("agents")

app = FastAPI(title="AI Business Agents", version="2.0.0")

# In-memory job tracking (also persisted to PostgreSQL)
jobs: dict = {}

# Database connection
DB_HOST = os.environ.get("POSTGRES_HOST", "prompt-template-db")
DB_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME = os.environ.get("POSTGRES_DB", "ai_mesh")
DB_USER = os.environ.get("POSTGRES_USER", "admin")
DB_PASS = os.environ.get("POSTGRES_PASSWORD", "")


def _persist_job(job_id: str, job_type: str, status: str, description: str = "",
                 result: str = None, triggered_by: str = "manual"):
    """Persist job status to PostgreSQL (best-effort, non-blocking)."""
    try:
        import psycopg2
        conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
        cur = conn.cursor()
        if status == "queued":
            cur.execute(
                "INSERT INTO agent_job_history (job_id, job_type, status, description, triggered_by) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (job_id, job_type, status, description, triggered_by),
            )
        else:
            cur.execute(
                "UPDATE agent_job_history SET status = %s, result = %s, completed_at = NOW() "
                "WHERE job_id = %s",
                (status, str(result)[:5000] if result else None, job_id),
            )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to persist job {job_id}: {e}")


class BuildRequest(BaseModel):
    business_description: str
    target_audience: Optional[str] = "general"


def run_in_background(job_id: str, job_type: str, func, *args):
    try:
        jobs[job_id]["status"] = "running"
        _persist_job(job_id, job_type, "running")
        result = func(*args)
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result
        jobs[job_id]["completed_at"] = time.time()
        _persist_job(job_id, job_type, "completed", result=result)
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["result"] = str(e)
        jobs[job_id]["completed_at"] = time.time()
        _persist_job(job_id, job_type, "failed", result=str(e))


@app.post("/v1/agents/strategy-session")
async def strategy_session(background_tasks: BackgroundTasks):
    """Trigger a strategy session. Returns job ID to poll for results."""
    from crew import run_strategy_session

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "queued", "job_type": "strategy-session", "result": None, "started_at": time.time(), "completed_at": None}
    _persist_job(job_id, "strategy-session", "queued")
    background_tasks.add_task(run_in_background, job_id, "strategy-session", run_strategy_session)
    return {"job_id": job_id, "status": "queued", "poll": f"/v1/agents/jobs/{job_id}"}


@app.post("/v1/agents/build-business")
async def build_business(request: BuildRequest, background_tasks: BackgroundTasks):
    """Trigger a full business build cycle. Returns job ID to poll for results."""
    from crew import run_business_build

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "queued", "job_type": "build-business", "result": None, "started_at": time.time(), "completed_at": None, "description": request.business_description}
    _persist_job(job_id, "build-business", "queued", description=request.business_description)
    background_tasks.add_task(run_in_background, job_id, "build-business", run_business_build, request.business_description, request.target_audience)
    return {"job_id": job_id, "status": "queued", "poll": f"/v1/agents/jobs/{job_id}"}


@app.get("/v1/agents/jobs/{job_id}")
async def get_job(job_id: str):
    """Check status of a running agent job."""
    if job_id not in jobs:
        return {"error": "Job not found"}
    return {"job_id": job_id, **jobs[job_id]}


@app.get("/v1/agents/jobs")
async def list_jobs():
    """List all agent jobs."""
    return {"jobs": [{"job_id": k, **v} for k, v in jobs.items()]}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "crewai-agents", "active_jobs": sum(1 for j in jobs.values() if j["status"] == "running")}
