"""
MeshCorp HQ API routes.

REST endpoints for project management, template listing, action queue.
WebSocket for real-time conversation streaming.
"""

import json
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from meshcorp.models import (
    CreateProjectRequest, FundProjectRequest, CEOMessageRequest,
    ConversationMessage, MessageRole,
)
from meshcorp.templates import list_templates, get_template
from meshcorp.projects import (
    create_project, get_project, list_projects, advance_project,
    fund_project, list_actions, resolve_action,
)
from meshcorp.conversation import run_discussion, extract_skill_tags
from meshcorp.db import get_pool

router = APIRouter(prefix="/api")

# Connected WebSocket clients
ws_clients: list[WebSocket] = []


async def broadcast_ws(event: str, data: dict):
    """Send event to all connected WebSocket clients."""
    message = json.dumps({"event": event, "data": data}, default=str)
    disconnected = []
    for ws in ws_clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in ws_clients:
            ws_clients.remove(ws)


# --- Templates ---

@router.get("/templates")
async def api_list_templates():
    return {"templates": [t.model_dump() for t in list_templates()]}


@router.get("/templates/{template_id}")
async def api_get_template(template_id: str):
    t = get_template(template_id)
    if not t:
        raise HTTPException(404, f"Template '{template_id}' not found")
    return t.model_dump()


# --- Projects ---

@router.post("/projects")
async def api_create_project(req: CreateProjectRequest):
    """Create a new project. AI plans milestones synchronously (takes ~30s)."""
    try:
        project = await create_project(req.template_id, req.description, req.model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await broadcast_ws("project_created", {
        "id": project.id,
        "name": project.name,
        "template_id": project.template_id,
        "status": project.status.value,
    })
    return project.model_dump()


@router.get("/projects")
async def api_list_projects(status: str | None = None):
    projects = await list_projects(status)
    return {"projects": [p.model_dump() for p in projects]}


@router.get("/projects/{project_id}")
async def api_get_project(project_id: str):
    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, f"Project '{project_id}' not found")

    actions = await list_actions(project_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        msg_rows = await conn.fetch(
            "SELECT * FROM mc_messages WHERE project_id = $1 ORDER BY created_at DESC LIMIT 50",
            project_id,
        )

    messages = [
        {
            "id": r["id"],
            "role": r["role"],
            "participant_name": r["participant_name"],
            "participant_model": r["participant_model"],
            "content": r["content"],
            "skill_tags": json.loads(r["skill_tags"]) if r["skill_tags"] else [],
            "milestone_id": r["milestone_id"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in reversed(msg_rows)
    ]

    return {
        "project": project.model_dump(),
        "actions": [a.model_dump() for a in actions],
        "messages": messages,
    }


@router.post("/projects/{project_id}/advance")
async def api_advance_project(project_id: str, background_tasks: BackgroundTasks):
    """Execute the next pending milestone in background."""
    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, f"Project '{project_id}' not found")

    async def on_message(msg: ConversationMessage):
        await broadcast_ws("message", {
            "project_id": project_id,
            "participant_name": msg.participant_name,
            "participant_model": msg.participant_model,
            "content": msg.content,
            "skill_tags": msg.skill_tags,
        })

    async def run_in_background():
        try:
            await advance_project(project_id, on_message=on_message)
            updated = await get_project(project_id)
            await broadcast_ws("milestone_completed", {
                "project_id": project_id,
                "status": updated.status.value if updated else "unknown",
            })
        except Exception as e:
            await broadcast_ws("error", {
                "project_id": project_id,
                "message": str(e),
            })

    background_tasks.add_task(run_in_background)
    return {"status": "advancing", "project_id": project_id}


@router.post("/projects/{project_id}/fund")
async def api_fund_project(project_id: str, req: FundProjectRequest):
    project = await get_project(project_id)
    if not project:
        raise HTTPException(404)
    await fund_project(project_id, req.amount)
    await broadcast_ws("project_funded", {
        "project_id": project_id,
        "amount": req.amount,
    })
    return {"status": "funded", "amount": req.amount}


@router.post("/projects/{project_id}/kill")
async def api_kill_project(project_id: str):
    project = await get_project(project_id)
    if not project:
        raise HTTPException(404)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE mc_projects SET status = 'killed', updated_at = NOW() WHERE id = $1",
            project_id,
        )
    await broadcast_ws("project_killed", {"project_id": project_id})
    return {"status": "killed"}


# --- CEO Chat ---

@router.post("/projects/{project_id}/chat")
async def api_ceo_chat(project_id: str, req: CEOMessageRequest, background_tasks: BackgroundTasks):
    """Send a CEO message into a project. Team responds in background."""
    project = await get_project(project_id)
    if not project:
        raise HTTPException(404)

    pool = await get_pool()
    msg_id = str(uuid.uuid4())[:8]
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO mc_messages (id, project_id, role, participant_name, content, skill_tags)
               VALUES ($1, $2, 'user', 'CEO', $3, $4)""",
            msg_id, project_id, req.content, json.dumps(extract_skill_tags(req.content)),
        )

    await broadcast_ws("message", {
        "project_id": project_id,
        "participant_name": "CEO",
        "content": req.content,
        "role": "user",
    })

    async def on_message(msg: ConversationMessage):
        await broadcast_ws("message", {
            "project_id": project_id,
            "participant_name": msg.participant_name,
            "participant_model": msg.participant_model,
            "content": msg.content,
            "skill_tags": msg.skill_tags,
        })

    async def run_discussion_bg():
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM mc_messages WHERE project_id = $1 ORDER BY created_at DESC LIMIT 30",
                    project_id,
                )

            history = [
                ConversationMessage(
                    id=r["id"], project_id=r["project_id"],
                    role=MessageRole(r["role"]),
                    participant_name=r["participant_name"] or "",
                    participant_model=r["participant_model"] or "",
                    content=r["content"],
                    skill_tags=json.loads(r["skill_tags"]) if r["skill_tags"] else [],
                )
                for r in reversed(rows)
            ]

            messages = await run_discussion(
                topic=req.content,
                team=project.team,
                project_context=f"Project: {project.name}\n{project.description}",
                history=history,
                on_message=on_message,
            )

            async with pool.acquire() as conn:
                for msg in messages:
                    msg.project_id = project_id
                    await conn.execute(
                        """INSERT INTO mc_messages (id, project_id, role, participant_name, participant_model, content, skill_tags)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        msg.id, msg.project_id, msg.role.value,
                        msg.participant_name, msg.participant_model, msg.content,
                        json.dumps(msg.skill_tags),
                    )
        except Exception as e:
            await broadcast_ws("error", {
                "project_id": project_id,
                "message": str(e),
            })

    background_tasks.add_task(run_discussion_bg)
    return {"status": "sent"}


# --- Actions ---

@router.get("/actions")
async def api_list_actions(project_id: str | None = None):
    actions = await list_actions(project_id)
    return {"actions": [a.model_dump() for a in actions]}


@router.post("/actions/{action_id}/resolve")
async def api_resolve_action(action_id: str):
    await resolve_action(action_id)
    await broadcast_ws("action_resolved", {"action_id": action_id})
    return {"status": "resolved"}


# --- Dashboard ---

@router.get("/dashboard")
async def api_dashboard():
    """Combined overview for the war room."""
    active = await list_projects("active")
    planning = await list_projects("planning")
    proposals = await list_projects("proposal")
    actions = await list_actions()

    total_allocated = sum(p.budget_allocated for p in active + planning)
    total_spent = sum(p.budget_spent for p in active + planning)

    return {
        "active_projects": [p.model_dump() for p in active],
        "planning_projects": [p.model_dump() for p in planning],
        "proposals": [p.model_dump() for p in proposals],
        "pending_actions": [a.model_dump() for a in actions],
        "financials": {
            "total_allocated": float(total_allocated),
            "total_spent": float(total_spent),
        },
    }


# --- WebSocket ---

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")

            if msg_type == "ping":
                await websocket.send_text(json.dumps({"event": "pong"}))

    except WebSocketDisconnect:
        if websocket in ws_clients:
            ws_clients.remove(websocket)
    except Exception:
        if websocket in ws_clients:
            ws_clients.remove(websocket)
