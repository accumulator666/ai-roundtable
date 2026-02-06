import time
import uuid
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="AI Business Agents", version="1.0.0")

# In-memory job tracking
jobs: dict = {}


class BuildRequest(BaseModel):
    business_description: str
    target_audience: Optional[str] = "general"


def run_in_background(job_id: str, func, *args):
    try:
        jobs[job_id]["status"] = "running"
        result = func(*args)
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result
        jobs[job_id]["completed_at"] = time.time()
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["result"] = str(e)
        jobs[job_id]["completed_at"] = time.time()


@app.post("/v1/agents/strategy-session")
async def strategy_session(background_tasks: BackgroundTasks):
    """Trigger a strategy session. Returns job ID to poll for results."""
    from crew import run_strategy_session

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "queued", "result": None, "started_at": time.time(), "completed_at": None}
    background_tasks.add_task(run_in_background, job_id, run_strategy_session)
    return {"job_id": job_id, "status": "queued", "poll": f"/v1/agents/jobs/{job_id}"}


@app.post("/v1/agents/build-business")
async def build_business(request: BuildRequest, background_tasks: BackgroundTasks):
    """Trigger a full business build cycle. Returns job ID to poll for results."""
    from crew import run_business_build

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "queued", "result": None, "started_at": time.time(), "completed_at": None}
    background_tasks.add_task(run_in_background, job_id, run_business_build, request.business_description, request.target_audience)
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
