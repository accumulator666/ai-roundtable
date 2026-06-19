"""
Base application for all company roundtables.
Each company imports this and gets a fully functional roundtable
scoped to its own team, budget, and database partition.

Usage in a company's main.py:
    from shared.base_app import create_company_app
    app = create_company_app()
"""

import os
import re
import json
import time
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Callable, Coroutine

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger("company")

# ============================================================
# Configuration (from environment)
# ============================================================

COMPANY_CODE = os.environ.get("COMPANY_CODE", "holding")
ROUTER_URL = os.environ.get("ROUTER_URL", "http://ai-mesh-router:8000")
AGENTS_URL = os.environ.get("AGENTS_URL", "http://ai-mesh-crewai:8000")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")

# Timeouts
DEFAULT_TIMEOUT: float = 120.0
LONG_TIMEOUT: float = 180.0

# Token limits
MAX_TOKENS_DEFAULT: int = 2048
TEMPERATURE_DEFAULT: float = 0.8

# History limits
HISTORY_LIMIT_ROUND: int = 30
HISTORY_LIMIT_SYNTHESIS: int = 40
MAX_CONVERSATION_HISTORY: int = 200

# Deliberation
SAFETY_CAP: int = 10
MAX_RETRIES: int = 3
RETRY_BACKOFF_BASE: float = 1.0

# Concurrency
MODEL_CONCURRENCY: int = int(os.environ.get("MODEL_CONCURRENCY", "8"))

# Per-model tuning defaults
MODEL_CONFIG_DEFAULT: dict[str, dict[str, Any]] = {
    "gpt-5.2": {"max_tokens": 2048, "temperature": 0.6, "timeout": LONG_TIMEOUT},
    "gpt-5": {"max_tokens": 2048, "temperature": 0.6, "timeout": LONG_TIMEOUT},
    "gpt-5-mini": {"max_tokens": 1024, "temperature": 0.7},
    "o4-mini": {"max_tokens": 1024, "temperature": 0.4, "timeout": LONG_TIMEOUT},
    "o3": {"max_tokens": 2048, "temperature": 0.4, "timeout": LONG_TIMEOUT},
    "o3-mini": {"max_tokens": 1024, "temperature": 0.4, "timeout": LONG_TIMEOUT},
    "o1": {"max_tokens": 2048, "temperature": 0.4, "timeout": LONG_TIMEOUT},
    "o1-pro": {"max_tokens": 2048, "temperature": 0.35, "timeout": LONG_TIMEOUT},
    "gpt-4o": {"max_tokens": 1536, "temperature": 0.6},
    "gpt-4o-mini": {"max_tokens": 1024, "temperature": 0.7},
}


def create_company_app(
    extra_startup: Optional[Callable] = None,
    extra_routes: Optional[Callable] = None,
) -> FastAPI:
    """
    Create a company-scoped roundtable FastAPI app.

    Args:
        extra_startup: async function called on startup (for company-specific init)
        extra_routes: function(app) to add company-specific routes
    """
    app_dir = Path(os.environ.get("APP_DIR", "/app"))

    # ============================================================
    # Load company-specific config
    # ============================================================

    def load_json(filename: str, default: Any) -> Any:
        path = app_dir / filename
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
        return default

    participants = load_json("participants.json", [])
    model_config_overrides = load_json("model_config.json", {})
    company_config = load_json("company_config.json", {
        "name": COMPANY_CODE.title(),
        "budget_limit_per_action": 20,
        "budget_limit_daily": 100,
    })
    presets = load_json("presets.json", {})

    # Merge model config
    model_config = {**MODEL_CONFIG_DEFAULT}
    for k, v in model_config_overrides.items():
        if isinstance(v, dict):
            model_config[k] = {**model_config.get(k, {}), **v}

    # ============================================================
    # App state
    # ============================================================

    conversation_history: list[dict[str, Any]] = []
    connected_clients: list[WebSocket] = []
    http_client: Optional[httpx.AsyncClient] = None
    model_semaphore = asyncio.Semaphore(MODEL_CONCURRENCY)
    session_lock = asyncio.Lock()
    model_stats: dict[str, dict[str, Any]] = {}
    deliberation_state = {"active": False, "paused": False, "stop_requested": False}
    max_deliberation_rounds: int = 0
    company_db_id: Optional[str] = None  # Set on startup
    start_time_val = time.time()
    active_jobs: dict[str, dict[str, Any]] = {}  # job_id -> {type, status, ...}
    pending_decisions: dict[str, dict[str, Any]] = {}  # decision_id -> {action, description, status}

    # ============================================================
    # FastAPI app
    # ============================================================

    app = FastAPI(
        title=f"{company_config.get('name', COMPANY_CODE)} Roundtable",
        version="4.0.0",
    )

    def get_client() -> httpx.AsyncClient:
        nonlocal http_client
        if http_client is None or http_client.is_closed:
            http_client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        return http_client

    def get_active():
        return [p for p in participants if p.get("enabled", False)]

    async def ws_broadcast(message: dict):
        dead = []
        for ws in connected_clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                connected_clients.remove(ws)
            except ValueError:
                pass

    def update_stats(model_id: str, ok: bool, elapsed_ms: float,
                     error_type: Optional[str] = None, error_msg: Optional[str] = None):
        stats = model_stats.setdefault(model_id, {
            "requests": 0, "success": 0, "errors": 0, "timeouts": 0,
            "avg_ms": 0.0, "last_ms": None, "last_error": None,
        })
        stats["requests"] += 1
        stats["last_ms"] = round(elapsed_ms, 2)
        stats["avg_ms"] = round(
            ((stats["avg_ms"] * (stats["requests"] - 1)) + elapsed_ms) / stats["requests"], 2
        )
        if ok:
            stats["success"] += 1
        else:
            stats["errors"] += 1
            if error_type == "timeout":
                stats["timeouts"] += 1
            stats["last_error"] = (error_msg or "")[:200]

    async def ask_model(
        model_id: str, model_name: str, messages: list[dict],
        max_retries: int = MAX_RETRIES, timeout: float = DEFAULT_TIMEOUT,
        max_tokens: Optional[int] = None, temperature: Optional[float] = None,
    ) -> str:
        last_error = ""
        start = time.perf_counter()
        for attempt in range(max_retries):
            try:
                cfg = model_config.get(model_id, {})
                req_max_tokens = max_tokens or cfg.get("max_tokens", MAX_TOKENS_DEFAULT)
                req_temp = temperature if temperature is not None else cfg.get("temperature", TEMPERATURE_DEFAULT)
                req_timeout = cfg.get("timeout", timeout)

                async with model_semaphore:
                    client = get_client()
                    resp = await client.post(
                        f"{ROUTER_URL}/v1/chat/completions",
                        json={
                            "model": model_id,
                            "messages": messages,
                            "max_tokens": req_max_tokens,
                            "temperature": req_temp,
                        },
                        timeout=req_timeout,
                    )
                if resp.status_code != 200:
                    last_error = f"[Error: HTTP {resp.status_code} from {model_name}]"
                    break
                data = resp.json()
                elapsed_ms = (time.perf_counter() - start) * 1000
                update_stats(model_id, True, elapsed_ms)
                usage = data.get("usage") or {}
                asyncio.create_task(_audit(
                    "model_call", actor=model_name, actor_type="model",
                    entity_type="model_call", success=True,
                    latency_ms=round(elapsed_ms),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    total_tokens=usage.get("total_tokens")))
                return data["choices"][0]["message"]["content"]
            except httpx.TimeoutException:
                last_error = f"[Timeout: {model_name} took too long]"
            except httpx.ConnectError:
                last_error = f"[Connection error: router unreachable]"
            except Exception as e:
                last_error = f"[Error: {model_name} — {str(e)[:120]}]"

            if attempt < max_retries - 1:
                await asyncio.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))

        elapsed_ms = (time.perf_counter() - start) * 1000
        update_stats(model_id, False, elapsed_ms, "error", last_error)
        asyncio.create_task(_audit(
            "model_call", actor=model_name, actor_type="model",
            entity_type="model_call", success=False,
            latency_ms=round(elapsed_ms), error=last_error[:200]))
        return last_error

    async def _audit(action: str, actor: str, actor_type: str = "system",
                     entity_type: Optional[str] = None, entity_id: Optional[str] = None,
                     **details) -> None:
        """Fire-and-forget audit. No-op if DB not initialized; log_event swallows errors."""
        if not company_db_id:
            return
        from shared.db import log_event
        await log_event(company_db_id, actor_type, actor, action,
                        entity_type, entity_id, details or None)

    def build_messages(participant: dict, history: list[dict], limit: int = HISTORY_LIMIT_ROUND) -> list[dict]:
        company_name = company_config.get("name", COMPANY_CODE)
        base_prompt = (
            f"You are in a {company_name} team meeting. "
            "Share your expert perspective. Be direct, specific, and honest."
        )
        if participant.get("persona"):
            system_prompt = f"{participant['persona']}\n\n{base_prompt}"
        else:
            system_prompt = base_prompt

        msgs: list[dict] = [{"role": "system", "content": system_prompt}]
        for msg in history[-limit:]:
            if msg["role"] == "user":
                msgs.append({"role": "user", "content": msg["content"]})
            elif msg.get("name") == participant["name"]:
                msgs.append({"role": "assistant", "content": msg["content"]})
            else:
                msgs.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})
        return msgs

    async def run_roundtable(user_message: str):
        nonlocal max_deliberation_rounds
        conversation_history.append({"role": "user", "name": "You", "content": user_message})
        await ws_broadcast({"type": "message", "role": "user", "name": "You", "content": user_message})

        active = get_active()
        if not active:
            await ws_broadcast({
                "type": "message", "role": "assistant", "name": "System",
                "color": "#666", "content": "No participants enabled. Enable some from the sidebar.",
            })
            return

        deliberation_state["active"] = True
        deliberation_state["stop_requested"] = False
        deliberation_state["paused"] = False
        await ws_broadcast({"type": "deliberation_state", "data": deliberation_state})

        total_rounds = min(max_deliberation_rounds, SAFETY_CAP)

        for round_num in range(total_rounds + 1):
            if deliberation_state["stop_requested"]:
                break
            while deliberation_state["paused"]:
                await asyncio.sleep(0.3)
                if deliberation_state["stop_requested"]:
                    break

            if round_num > 0:
                await ws_broadcast({
                    "type": "status", "message": f"Round {round_num} of {total_rounds}",
                    "phase": "round_start", "round": round_num,
                })

            tasks = []
            for p in active:
                msgs = build_messages(p, conversation_history)
                tasks.append((p, ask_model(p["id"], p["name"], msgs)))

            for p, task in tasks:
                response = await task
                conversation_history.append({
                    "role": "assistant", "name": p["name"], "content": response,
                })
                await ws_broadcast({
                    "type": "message", "role": "assistant",
                    "name": p["name"], "color": p.get("color", "#888"),
                    "badge": p.get("type"), "content": response,
                })

        # Synthesis round — if multiple participants discussed, synthesize a final answer
        if len(active) > 1 and not deliberation_state["stop_requested"]:
            synthesizer = active[0]
            synthesis_prompt = (
                f"You are the lead synthesizer for {company_config.get('name', COMPANY_CODE)}. "
                "Your team just discussed the topic above. Produce ONE comprehensive, actionable final answer that:\n"
                "- Incorporates the best ideas from all team members\n"
                "- Resolves disagreements (explain which side won and why)\n"
                "- Includes specific next steps and recommendations\n"
                "- Notes risks or caveats the team flagged\n\n"
                "If the team agreed to BUILD, CREATE, or LAUNCH a product/service/project, include:\n"
                "  [ACTION:project] one-line description of what to build [/ACTION]\n"
                "This will automatically kick off project mode — breaking it into tasks, assigning to team members, and executing.\n"
                "If the team agreed to do a STRATEGY REVIEW, include:\n"
                "  [ACTION:strategy-session] reason [/ACTION]\n"
            )
            if synthesizer.get("persona"):
                synthesis_prompt = f"{synthesizer['persona']}\n\n{synthesis_prompt}"
            syn_msgs: list[dict] = [{"role": "system", "content": synthesis_prompt}]
            for msg in conversation_history[-HISTORY_LIMIT_SYNTHESIS:]:
                if msg["role"] == "user":
                    syn_msgs.append({"role": "user", "content": msg["content"]})
                elif msg.get("name") == synthesizer["name"]:
                    syn_msgs.append({"role": "assistant", "content": msg["content"]})
                else:
                    syn_msgs.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})

            await ws_broadcast({"type": "status", "message": "Synthesizing final answer...", "phase": "synthesis", "round": None})
            final = await ask_model(synthesizer["id"], "Synthesizer", syn_msgs, timeout=LONG_TIMEOUT)
            conversation_history.append({"role": "assistant", "name": "Synthesizer", "content": final})
            await ws_broadcast({
                "type": "message", "role": "assistant", "name": "Final Answer",
                "color": "#fbbf24", "badge": "synthesis", "content": final,
            })

            # Detect actionable decisions from synthesis
            asyncio.create_task(detect_and_execute_decisions(final))

        # Trim history
        if len(conversation_history) > MAX_CONVERSATION_HISTORY:
            del conversation_history[:len(conversation_history) - MAX_CONVERSATION_HISTORY]

        deliberation_state["active"] = False
        await ws_broadcast({"type": "deliberation_state", "data": deliberation_state})
        await ws_broadcast({"type": "deliberation_complete"})

    async def run_serialized(job_factory, websocket=None):
        if session_lock.locked():
            msg = {
                "type": "message", "role": "assistant", "name": "System",
                "color": "#666", "content": "Roundtable is busy. Wait or press Stop.",
            }
            if websocket:
                await websocket.send_json(msg)
            return
        async with session_lock:
            try:
                await job_factory()
            except Exception as e:
                await ws_broadcast({
                    "type": "message", "role": "assistant", "name": "System",
                    "color": "#b91c1c", "content": f"Error: {str(e)[:200]}",
                })
                deliberation_state["active"] = False

    # ============================================================
    # Agent job integration (CrewAI)
    # ============================================================

    async def trigger_agent_job(job_type: str, description: str = "", audience: str = "general"):
        """Trigger a CrewAI agent job and start polling for updates."""
        client = get_client()
        try:
            if job_type == "strategy-session":
                resp = await client.post(f"{AGENTS_URL}/v1/agents/strategy-session", timeout=30.0)
            elif job_type == "build-business":
                resp = await client.post(
                    f"{AGENTS_URL}/v1/agents/build-business",
                    json={"business_description": description, "target_audience": audience},
                    timeout=30.0,
                )
            else:
                await ws_broadcast({"type": "job_error", "error": f"Unknown job type: {job_type}"})
                return

            data = resp.json()
            job_id = data.get("job_id", "unknown")
            active_jobs[job_id] = {
                "type": job_type, "status": "queued", "description": description,
                "started_at": time.time(),
            }
            await ws_broadcast({
                "type": "job_started", "job_id": job_id,
                "job_type": job_type, "description": description,
            })
            asyncio.create_task(poll_job_status(job_id))
        except Exception as e:
            await ws_broadcast({"type": "job_error", "error": str(e)[:200]})

    async def poll_job_status(job_id: str, interval: float = 5.0, max_polls: int = 360):
        """Poll agents API for job completion and broadcast updates."""
        client = get_client()
        last_status = None
        for _ in range(max_polls):
            await asyncio.sleep(interval)
            try:
                resp = await client.get(f"{AGENTS_URL}/v1/agents/jobs/{job_id}", timeout=10.0)
                job = resp.json()
                status = job.get("status")
                if status != last_status:
                    last_status = status
                    if job_id in active_jobs:
                        active_jobs[job_id]["status"] = status
                    await ws_broadcast({
                        "type": "job_update", "job_id": job_id,
                        "status": status,
                        "result": job.get("result") if status in ("completed", "failed") else None,
                    })
                if status in ("completed", "failed"):
                    if status == "completed" and job.get("result"):
                        result_text = str(job["result"])[:3000]
                        conversation_history.append({
                            "role": "assistant", "name": "Agent System",
                            "content": f"**[Job completed: {active_jobs.get(job_id, {}).get('type', job_id)}]**\n\n{result_text}",
                        })
                        await ws_broadcast({
                            "type": "message", "role": "assistant",
                            "name": "Agent System", "color": "#f59e0b",
                            "badge": "agent", "content": f"**[Job completed]**\n\n{result_text}",
                        })
                    return
            except Exception:
                pass

    # ============================================================
    # Decision detection (post-synthesis)
    # ============================================================

    DECISION_PATTERNS = {
        "build-business": [
            r"(?:let's|we should|I recommend|decision:|agreed to)\s*(?:build|create|launch|develop)\s+(?:a\s+)?(.+?)(?:\.|$)",
        ],
        "strategy-session": [
            r"(?:need to|should)\s+(?:run|do)\s+(?:a\s+)?strategy\s+(?:session|review)",
        ],
        "project": [
            r"\[ACTION:project\]\s*(.*?)\s*\[/ACTION\]",
        ],
    }

    async def detect_and_execute_decisions(synthesis_text: str):
        """Parse synthesis for actionable decisions. Auto-triggers projects or stores as pending."""
        import uuid as _uuid
        # Check for explicit [ACTION:type] description [/ACTION] tags
        explicit = re.findall(r'\[ACTION:([\w-]+)\]\s*(.*?)\s*\[/ACTION\]', synthesis_text, re.DOTALL)
        if explicit:
            for action_type, description in explicit:
                # Auto-trigger project mode for project actions
                if action_type == "project":
                    asyncio.create_task(run_project(description.strip()))
                    continue
                decision_id = _uuid.uuid4().hex[:8]
                pending_decisions[decision_id] = {
                    "action": action_type, "description": description.strip(),
                    "status": "pending",
                }
                await _audit("decision_detected", actor="Synthesizer", actor_type="system",
                             entity_type="decision", entity_id=decision_id,
                             description=description)
                await ws_broadcast({
                    "type": "decision_detected", "decision_id": decision_id,
                    "action": action_type, "description": description.strip()[:200],
                })
            return

        # Fallback: regex pattern matching
        text_lower = synthesis_text.lower()
        for action_type, patterns in DECISION_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, text_lower)
                if match:
                    desc = match.group(1) if match.lastindex else synthesis_text[:200]
                    decision_id = _uuid.uuid4().hex[:8]
                    pending_decisions[decision_id] = {
                        "action": action_type, "description": desc.strip(),
                        "status": "pending",
                    }
                    await _audit("decision_detected", actor="Synthesizer", actor_type="system",
                                 entity_type="decision", entity_id=decision_id,
                                 description=desc)
                    await ws_broadcast({
                        "type": "decision_detected", "decision_id": decision_id,
                        "action": action_type, "description": desc.strip()[:200],
                    })
                    return

    # ============================================================
    # Project Mode — CEO pitches, team breaks it down, executes
    # ============================================================

    active_projects: dict[str, dict] = {}

    TASK_BREAKDOWN_PROMPT = """You are the project manager at {company_name}. Break this pitch into tasks for YOUR team.

Your team members and their skills:
{team_roster}

Pitch: {pitch}

Respond ONLY with valid JSON (no markdown). Create 3-10 tasks assigned to specific team members:

{{
  "project_name": "short name",
  "summary": "1-2 sentence summary",
  "revenue_target": "how much money this can make monthly",
  "tasks": [
    {{
      "title": "short task title",
      "description": "specific deliverable (2-3 sentences)",
      "assignee": "exact team member name from roster above",
      "priority": "high/medium/low"
    }}
  ]
}}

Rules:
- ONLY assign to team members listed above
- Each task should be completable by one person independently
- Tasks should produce a concrete deliverable (code, report, plan, design)
- Include what each person needs to deliver, not just "think about X"
- Order tasks logically but they will run in parallel"""

    async def run_project(pitch: str, model: str = "gpt-5.2"):
        """Full project lifecycle within this company's roundtable."""
        import uuid as _uuid
        project_id = _uuid.uuid4().hex[:10]
        company_name = company_config.get("name", COMPANY_CODE)

        await ws_broadcast({
            "type": "message", "role": "assistant", "name": "Project Manager",
            "color": "#f59e0b", "badge": "project",
            "content": f"**New Project Initiated**\n\n*\"{pitch}\"*\n\nBreaking down into tasks for the {company_name} team...",
        })
        conversation_history.append({
            "role": "assistant", "name": "Project Manager",
            "content": f"New project: {pitch}",
        })

        # Build roster of all participants in this company
        roster_lines = []
        for p in participants:
            persona_short = (p.get("persona") or "")[:80]
            roster_lines.append(f"- {p['name']}: {persona_short}")
        roster_text = "\n".join(roster_lines)

        prompt = TASK_BREAKDOWN_PROMPT.format(
            company_name=company_name,
            team_roster=roster_text,
            pitch=pitch,
        )

        # Use AI to break pitch into tasks
        client = get_client()
        try:
            resp = await client.post(
                f"{ROUTER_URL}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a project manager. Respond ONLY with valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 3000,
                    "temperature": 0.4,
                },
                timeout=120.0,
            )
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()
            breakdown = json.loads(raw)
        except Exception as e:
            await ws_broadcast({
                "type": "message", "role": "assistant", "name": "Project Manager",
                "color": "#ef4444", "badge": "error",
                "content": f"Failed to break down project: {str(e)[:200]}",
            })
            return

        tasks = breakdown.get("tasks", [])
        project_name = breakdown.get("project_name", "Unnamed")
        revenue = breakdown.get("revenue_target", "TBD")

        # Show the plan in chat
        task_list = "\n".join(
            f"  {i+1}. **{t['title']}** → {t.get('assignee', '?')} ({t.get('priority', 'medium')})"
            for i, t in enumerate(tasks)
        )
        await ws_broadcast({
            "type": "message", "role": "assistant", "name": "Project Manager",
            "color": "#f59e0b", "badge": "project",
            "content": (
                f"**Project: {project_name}**\n"
                f"Revenue target: {revenue}\n"
                f"Summary: {breakdown.get('summary', '')}\n\n"
                f"**Task Assignments ({len(tasks)} tasks):**\n{task_list}\n\n"
                f"Executing all tasks in parallel now..."
            ),
        })

        # Store project
        project = {
            "id": project_id,
            "name": project_name,
            "pitch": pitch,
            "breakdown": breakdown,
            "tasks": tasks,
            "status": "executing",
            "results": {},
        }
        active_projects[project_id] = project

        # Execute all tasks in parallel
        async def execute_task(task_def: dict) -> dict:
            assignee_name = task_def.get("assignee", "")
            # Find the participant
            assignee = next((p for p in participants if p["name"] == assignee_name), None)
            if not assignee:
                # Fuzzy match
                assignee = next(
                    (p for p in participants if assignee_name.lower() in p["name"].lower()),
                    participants[0] if participants else None,
                )
            if not assignee:
                return {**task_def, "status": "error", "result": "No matching team member found"}

            await ws_broadcast({
                "type": "message", "role": "assistant", "name": "Project Manager",
                "color": "#6b7280", "badge": "task",
                "content": f"**{assignee['name']}** is working on: *{task_def['title']}*",
            })

            task_prompt = (
                f"**You are working on a project for {company_name}.**\n\n"
                f"Project: {project_name}\n"
                f"Context: {breakdown.get('summary', pitch)}\n\n"
                f"**Your assigned task: {task_def['title']}**\n"
                f"{task_def.get('description', '')}\n\n"
                f"Deliver a thorough, specific, actionable response. "
                f"Include concrete details: names, numbers, code, timelines, or specs as appropriate. "
                f"This is real work that will be combined with other team members' deliverables."
            )

            msgs = [
                {"role": "system", "content": assignee.get("persona", f"You are {assignee['name']}.")},
                {"role": "user", "content": task_prompt},
            ]

            try:
                result = await ask_model(assignee["id"], assignee["name"], msgs, timeout=LONG_TIMEOUT)
                return {**task_def, "status": "completed", "result": result, "done_by": assignee["name"]}
            except Exception as e:
                return {**task_def, "status": "error", "result": str(e)[:200], "done_by": assignee["name"]}

        # Run all tasks in parallel
        results = await asyncio.gather(*[execute_task(t) for t in tasks])

        # Show each result in chat
        completed = 0
        for r in results:
            status_icon = "done" if r["status"] == "completed" else "error"
            color = "#10b981" if r["status"] == "completed" else "#ef4444"
            if r["status"] == "completed":
                completed += 1
            result_preview = (r.get("result") or "")[:800]
            await ws_broadcast({
                "type": "message", "role": "assistant",
                "name": r.get("done_by", r.get("assignee", "Unknown")),
                "color": color, "badge": status_icon,
                "content": f"**Task: {r['title']}**\n\n{result_preview}",
            })
            conversation_history.append({
                "role": "assistant", "name": r.get("done_by", "Unknown"),
                "content": f"[Task: {r['title']}]\n\n{r.get('result', 'Error')}",
            })

        project["results"] = results
        project["status"] = "integrating"

        # Integration: combine all results
        await ws_broadcast({
            "type": "message", "role": "assistant", "name": "Project Manager",
            "color": "#f59e0b", "badge": "project",
            "content": f"**{completed}/{len(tasks)} tasks completed.** Synthesizing final deliverable...",
        })

        results_text = "\n\n---\n\n".join(
            f"### {r['title']} (by {r.get('done_by', '?')})\n{r.get('result', 'Error')}"
            for r in results if r["status"] == "completed"
        )

        synth_prompt = (
            f"You are the project lead at {company_name}. Your team just completed their tasks for: **{project_name}**\n\n"
            f"Original pitch: {pitch}\n\n"
            f"Here are all the completed deliverables:\n\n{results_text}\n\n"
            f"Create ONE comprehensive final deliverable that:\n"
            f"1. Combines all team outputs into a cohesive plan/product\n"
            f"2. Identifies gaps or conflicts and resolves them\n"
            f"3. Lists concrete next steps with owners and deadlines\n"
            f"4. Estimates revenue potential and timeline to first dollar\n"
            f"5. Gives a readiness score (1-10) and what's needed to ship"
        )

        lead = participants[0] if participants else {"id": "gpt-5.2", "name": "Lead"}
        synth_msgs = [
            {"role": "system", "content": lead.get("persona", "You are the project lead.")},
            {"role": "user", "content": synth_prompt},
        ]

        try:
            synthesis = await ask_model(lead["id"], "Project Lead", synth_msgs, timeout=LONG_TIMEOUT)
        except Exception as e:
            synthesis = f"Integration failed: {str(e)[:200]}"

        conversation_history.append({
            "role": "assistant", "name": "Project Synthesis",
            "content": synthesis,
        })
        await ws_broadcast({
            "type": "message", "role": "assistant", "name": "Project Deliverable",
            "color": "#fbbf24", "badge": "synthesis",
            "content": f"**{project_name} — Final Deliverable**\n\n{synthesis}",
        })

        project["synthesis"] = synthesis
        project["status"] = "completed"

        # Persist to DB
        try:
            from shared.db import save_project
            await save_project({
                "id": project_id,
                "pitch": pitch,
                "outline": breakdown,
                "tasks": [
                    {
                        "id": _uuid.uuid4().hex[:8],
                        "title": r["title"],
                        "description": r.get("description", ""),
                        "skill": r.get("assignee", ""),
                        "phase": "",
                        "priority": r.get("priority", "medium"),
                        "assigned_company": COMPANY_CODE,
                        "assigned_participants": [r.get("done_by", "")],
                        "status": r["status"],
                        "result": r.get("result"),
                    }
                    for r in results
                ],
                "status": "completed",
            })
        except Exception:
            pass

        await ws_broadcast({
            "type": "project_complete",
            "project_id": project_id,
            "name": project_name,
            "completed": completed,
            "total": len(tasks),
        })

    # ============================================================
    # Startup / shutdown
    # ============================================================

    @app.on_event("startup")
    async def startup():
        nonlocal company_db_id
        get_client()

        # Initialize database and get company ID
        try:
            from shared.db import get_pool, get_company_by_code
            await get_pool()  # Auto-creates tables
            company = await get_company_by_code(COMPANY_CODE)
            if company:
                company_db_id = company["id"]
                logger.info(f"Company {COMPANY_CODE} initialized (db_id={company_db_id})")
        except Exception as e:
            logger.warning(f"Database not available: {e} — running without DB")

        # Start Redis listener for cross-company messages
        try:
            from shared.company_comms import listen
            asyncio.create_task(listen(COMPANY_CODE, handle_cross_company_message))
            logger.info(f"Listening for cross-company messages on {COMPANY_CODE}")
        except Exception as e:
            logger.warning(f"Redis not available: {e} — running without cross-company comms")

        if extra_startup:
            await extra_startup()

    @app.on_event("shutdown")
    async def shutdown():
        nonlocal http_client
        if http_client and not http_client.is_closed:
            await http_client.aclose()
        try:
            from shared.db import close_pool
            await close_pool()
        except Exception:
            pass
        try:
            from shared.company_comms import close_redis
            await close_redis()
        except Exception:
            pass

    async def handle_cross_company_message(envelope: dict):
        """Handle incoming messages from other companies."""
        payload = envelope.get("payload", {})
        msg_type = payload.get("type", "unknown")
        from_company = envelope.get("from", "unknown")

        await ws_broadcast({
            "type": "cross_company",
            "from": from_company,
            "message_type": msg_type,
            "payload": payload,
        })

    # ============================================================
    # WebSocket
    # ============================================================

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        nonlocal max_deliberation_rounds
        await websocket.accept()
        connected_clients.append(websocket)

        await websocket.send_json({"type": "company_info", "code": COMPANY_CODE, "config": company_config})
        await websocket.send_json({"type": "participants", "data": participants})
        await websocket.send_json({"type": "settings", "max_rounds": max_deliberation_rounds})
        await websocket.send_json({"type": "deliberation_state", "data": deliberation_state})
        await websocket.send_json({"type": "presets", "data": presets})

        for msg in conversation_history:
            p = next((p for p in participants if p["name"] == msg.get("name")), None)
            await websocket.send_json({
                "type": "message", "role": msg["role"],
                "name": msg.get("name", "You"),
                "color": p["color"] if p else "#ffffff",
                "badge": p["type"] if p else None,
                "content": msg["content"],
            })

        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "message":
                    asyncio.create_task(
                        run_serialized(lambda: run_roundtable(data["content"]), websocket)
                    )
                elif data.get("type") == "toggle":
                    name = data.get("name")
                    for p in participants:
                        if p["name"] == name:
                            p["enabled"] = not p["enabled"]
                            break
                    await ws_broadcast({"type": "participants", "data": participants})
                elif data.get("type") == "stop":
                    deliberation_state["stop_requested"] = True
                    deliberation_state["paused"] = False
                elif data.get("type") == "pause":
                    if deliberation_state["active"]:
                        deliberation_state["paused"] = True
                elif data.get("type") == "resume":
                    content = data.get("content", "").strip()
                    if content:
                        conversation_history.append({"role": "user", "name": "You", "content": content})
                        await ws_broadcast({"type": "message", "role": "user", "name": "You", "content": content})
                    deliberation_state["paused"] = False
                elif data.get("type") == "activate_preset":
                    preset_id = data.get("preset")
                    preset = presets.get(preset_id)
                    if preset:
                        member_names = [m.lower() for m in preset.get("members", [])]
                        for p in participants:
                            p["enabled"] = p["name"].lower() in member_names
                        await ws_broadcast({"type": "participants", "data": participants})
                elif data.get("type") == "set_max_rounds":
                    max_deliberation_rounds = max(0, min(10, int(data.get("rounds", 0))))
                    await ws_broadcast({"type": "settings", "max_rounds": max_deliberation_rounds})
                elif data.get("type") == "pitch":
                    # Project mode: break pitch into tasks, assign, execute, integrate
                    pitch_text = data.get("content", "").strip()
                    pitch_model = data.get("model", "gpt-5.2")
                    if pitch_text:
                        asyncio.create_task(run_project(pitch_text, model=pitch_model))
                elif data.get("type") == "trigger_job":
                    asyncio.create_task(trigger_agent_job(
                        data.get("job_type", "strategy-session"),
                        data.get("business_description", ""),
                        data.get("target_audience", "general"),
                    ))
                elif data.get("type") == "approve_decision":
                    did = data.get("decision_id", "")
                    decision = pending_decisions.get(did)
                    if decision and decision["status"] == "pending":
                        decision["status"] = "executing"
                        await _audit("decision_approved", actor="CEO", actor_type="agent",
                                     entity_type="decision", entity_id=did)
                        await ws_broadcast({"type": "decision_executing", "decision_id": did})
                        asyncio.create_task(trigger_agent_job(
                            decision["action"], decision["description"],
                        ))
                elif data.get("type") == "reject_decision":
                    did = data.get("decision_id", "")
                    if did in pending_decisions:
                        pending_decisions[did]["status"] = "rejected"
                        await _audit("decision_rejected", actor="CEO", actor_type="agent",
                                     entity_type="decision", entity_id=did)
                        await ws_broadcast({"type": "decision_rejected", "decision_id": did})
        except WebSocketDisconnect:
            if websocket in connected_clients:
                connected_clients.remove(websocket)

    # ============================================================
    # REST endpoints
    # ============================================================

    @app.get("/", response_class=HTMLResponse)
    async def index():
        html_path = app_dir / "index.html"
        if html_path.exists():
            return HTMLResponse(content=html_path.read_text())
        return HTMLResponse(content=f"<h1>{company_config.get('name', COMPANY_CODE)} — No UI yet</h1>")

    @app.get("/health")
    async def health():
        active = get_active()
        uptime = int(time.time() - start_time_val)
        h, r = divmod(uptime, 3600)
        m, s = divmod(r, 60)
        return {
            "status": "ok",
            "company": COMPANY_CODE,
            "company_name": company_config.get("name", COMPANY_CODE),
            "active": [p["name"] for p in active],
            "total_participants": len(participants),
            "uptime": f"{h}h {m}m {s}s",
            "model_stats": model_stats,
        }

    @app.get("/api/participants")
    async def list_participants():
        return participants

    @app.put("/api/participants/{name}")
    async def update_participant(name: str, enabled: Optional[bool] = None):
        for p in participants:
            if p["name"] == name:
                if enabled is not None:
                    p["enabled"] = enabled
                await ws_broadcast({"type": "participants", "data": participants})
                return p
        return JSONResponse({"error": "not found"}, status_code=404)

    @app.get("/api/presets")
    async def list_presets():
        return presets

    @app.get("/api/company")
    async def company_info():
        return {
            "code": COMPANY_CODE,
            "config": company_config,
            "db_id": str(company_db_id) if company_db_id else None,
        }

    @app.get("/api/model-stats")
    async def get_model_stats():
        return {"models": model_stats}

    @app.get("/api/minutes")
    async def get_minutes():
        lines = [
            f"# {company_config.get('name', COMPANY_CODE)} — Meeting Minutes",
            f"\n**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Company:** {COMPANY_CODE}",
            "",
        ]
        active_names = [p["name"] for p in get_active()]
        if active_names:
            lines.append(f"**Active participants:** {', '.join(active_names)}")
        lines.append("\n---\n")

        for msg in conversation_history:
            name = msg.get("name", "Unknown")
            content = msg.get("content", "")
            if msg["role"] == "user":
                lines.append(f"## User\n\n{content}\n")
            else:
                lines.append(f"### {name}\n\n{content}\n")
        return {"markdown": "\n".join(lines)}

    @app.post("/api/clear")
    async def clear_history():
        conversation_history.clear()
        await ws_broadcast({"type": "history_cleared"})
        return {"status": "cleared"}

    @app.get("/api/pnl")
    async def get_pnl():
        if not company_db_id:
            return {"error": "database not connected"}
        try:
            from shared.db import get_company_pnl
            return await get_company_pnl(company_db_id)
        except Exception as e:
            return {"error": str(e)}

    @app.get("/api/decisions")
    async def get_decisions():
        if not company_db_id:
            return {"error": "database not connected"}
        try:
            from shared.db import get_recent_decisions
            return await get_recent_decisions(company_db_id)
        except Exception as e:
            return {"error": str(e)}

    @app.get("/api/activity")
    async def api_activity(limit: int = 100, action: Optional[str] = None):
        """Append-only audit trail for this company (newest first)."""
        if not company_db_id:
            return {"company": COMPANY_CODE, "count": 0, "activity": []}
        from shared.db import get_activity
        rows = await get_activity(company_db_id, limit=limit, action=action)
        for r in rows:
            r["id"] = str(r["id"])
            if r.get("company_id"):
                r["company_id"] = str(r["company_id"])
            if r.get("occurred_at"):
                r["occurred_at"] = r["occurred_at"].isoformat()
            if isinstance(r.get("details"), str):
                try:
                    r["details"] = json.loads(r["details"])
                except (json.JSONDecodeError, TypeError):
                    pass
        return {"company": COMPANY_CODE, "count": len(rows), "activity": rows}

    # Agent job endpoints
    @app.get("/api/dashboard")
    async def dashboard():
        """Combined dashboard: P&L, active jobs, recent decisions, pending decisions."""
        result: dict[str, Any] = {
            "company": COMPANY_CODE,
            "active_jobs": {jid: {k: v for k, v in j.items() if k != "started_at"}
                           for jid, j in active_jobs.items()},
            "pending_decisions": {did: d for did, d in pending_decisions.items()
                                 if d["status"] == "pending"},
        }
        if company_db_id:
            try:
                from shared.db import get_company_pnl, get_recent_decisions
                result["pnl"] = await get_company_pnl(company_db_id)
                result["decisions"] = await get_recent_decisions(company_db_id, limit=10)
            except Exception as e:
                result["db_error"] = str(e)[:200]
        # Fetch agent jobs from CrewAI
        try:
            client = get_client()
            resp = await client.get(f"{AGENTS_URL}/v1/agents/jobs", timeout=10.0)
            result["agent_jobs"] = resp.json().get("jobs", [])
        except Exception:
            result["agent_jobs"] = []
        return result

    @app.get("/api/agent-jobs")
    async def list_agent_jobs():
        """Proxy to CrewAI agents job list."""
        try:
            client = get_client()
            resp = await client.get(f"{AGENTS_URL}/v1/agents/jobs", timeout=10.0)
            return resp.json()
        except Exception as e:
            return {"error": str(e)[:200]}

    @app.post("/api/trigger-job")
    async def trigger_job_endpoint(request: dict):
        """Trigger a CrewAI agent job."""
        job_type = request.get("job_type", "strategy-session")
        desc = request.get("business_description", "")
        audience = request.get("target_audience", "general")
        asyncio.create_task(trigger_agent_job(job_type, desc, audience))
        return {"status": "triggered", "job_type": job_type}

    # Cross-company endpoints
    @app.post("/api/send-to/{target_company}")
    async def send_to_company(target_company: str, message: dict):
        try:
            from shared.company_comms import send_to_company as _send
            await _send(target_company, message, COMPANY_CODE)
            return {"status": "sent"}
        except Exception as e:
            return {"error": str(e)}

    @app.post("/api/pitch")
    async def pitch_project(request: dict):
        """Pitch a project to this company's team. Breaks into tasks, executes in parallel, integrates."""
        pitch_text = request.get("pitch", "").strip()
        if not pitch_text:
            return {"error": "pitch is required"}
        model = request.get("model", "gpt-5.2")
        asyncio.create_task(run_project(pitch_text, model=model))
        return {"status": "project_started", "company": COMPANY_CODE}

    @app.get("/api/active-projects")
    async def list_active_projects():
        return {"projects": [
            {"id": p["id"], "name": p["name"], "status": p["status"],
             "tasks": len(p.get("tasks", [])),
             "completed": sum(1 for r in p.get("results", []) if isinstance(r, dict) and r.get("status") == "completed")}
            for p in active_projects.values()
        ]}

    @app.post("/api/request-funding")
    async def request_funding_endpoint(request: dict):
        try:
            from shared.company_comms import request_funding
            await request_funding(COMPANY_CODE, request.get("amount", 0), request.get("reason", ""))
            return {"status": "funding request sent to MeshCapital"}
        except Exception as e:
            return {"error": str(e)}

    # ============================================================
    # Task execution (receives work from the project orchestrator)
    # ============================================================

    @app.post("/api/execute-task")
    async def execute_task(request: dict):
        """
        Receive a task from the holding company orchestrator.
        Temporarily enables the specified participants, runs a focused
        roundtable discussion on the task, and returns the result.

        Body: {
            "task_id": "abc123",
            "title": "Build the REST API",
            "description": "Design and implement...",
            "skill": "backend",
            "participants": ["Backend Dev", "Full-Stack Dev"],
            "project_context": "We're building a SaaS tool for..."
        }
        """
        task_title = request.get("title", "Untitled Task")
        task_desc = request.get("description", "")
        skill = request.get("skill", "")
        target_names = request.get("participants", [])
        project_context = request.get("project_context", "")

        # Save and restore participant enabled state
        original_state = {p["name"]: p.get("enabled", False) for p in participants}

        # Enable only the requested participants
        matched = []
        for p in participants:
            if p["name"] in target_names:
                p["enabled"] = True
                matched.append(p)
            else:
                p["enabled"] = False

        if not matched:
            # Fallback: enable first participant
            if participants:
                participants[0]["enabled"] = True
                matched = [participants[0]]

        company_name = company_config.get("name", COMPANY_CODE)
        task_prompt = (
            f"**Project Context:** {project_context}\n\n"
            f"**Your Task:** {task_title}\n\n"
            f"**Details:** {task_desc}\n\n"
            f"You are working on this task for {company_name}. "
            f"Provide a thorough, actionable response. "
            f"Include specific recommendations, technical details, or deliverables as appropriate for your role. "
            f"Be concrete — include names, numbers, timelines, or code snippets where relevant."
        )

        # Run a focused roundtable with just these participants
        responses = []
        for p in matched:
            msgs = build_messages(p, [{"role": "user", "name": "Project Orchestrator", "content": task_prompt}])
            try:
                response = await ask_model(p["id"], p["name"], msgs, timeout=LONG_TIMEOUT)
                responses.append(f"**{p['name']}:**\n{response}")
            except Exception as e:
                responses.append(f"**{p['name']}:** [Error: {str(e)[:100]}]")

        # If multiple participants, synthesize
        if len(responses) > 1:
            synth_msgs = [
                {"role": "system", "content": (
                    f"You are the lead on this task at {company_name}. "
                    "Combine your team's responses into ONE cohesive deliverable. "
                    "Resolve any disagreements. Be specific and actionable."
                )},
                {"role": "user", "content": (
                    f"Task: {task_title}\n\n"
                    f"Team responses:\n\n" + "\n\n---\n\n".join(responses) +
                    "\n\nCombine these into a single, complete deliverable."
                )},
            ]
            synthesizer = matched[0]
            result = await ask_model(synthesizer["id"], "Task Synthesizer", synth_msgs, timeout=LONG_TIMEOUT)
        else:
            result = responses[0] if responses else "No participants available"

        # Restore original enabled state
        for p in participants:
            p["enabled"] = original_state.get(p["name"], False)

        # Broadcast that this company worked on a task
        await ws_broadcast({
            "type": "message", "role": "assistant", "name": "Task System",
            "color": "#f59e0b", "badge": "orchestrator",
            "content": f"**Completed task:** {task_title}\n\n{result[:500]}{'...' if len(result) > 500 else ''}",
        })

        return {"task_id": request.get("task_id"), "result": result, "participants_used": [p["name"] for p in matched]}

    # Expose ws_broadcast for the orchestrator (holding company uses this)
    app._ws_broadcast = ws_broadcast

    # Add company-specific routes
    if extra_routes:
        extra_routes(app)

    return app
