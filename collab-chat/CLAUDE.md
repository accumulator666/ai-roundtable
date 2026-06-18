# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Collab Chat is a WebSocket-based multi-AI roundtable and AI company platform. A single FastAPI backend (`main.py`, ~2900 lines) orchestrates 65+ AI participants — raw models and persona-based agents — through the AI Mesh router, running multi-round deliberation and producing synthesized answers. It includes task boards, project management, CrewAI job integration, and decision tracking. The frontend is a single-page app (`index.html`, ~2900 lines).

## Commands

```bash
# Restart after code changes (volume-mounted, no build step)
docker restart ai-mesh-collab-chat

# View logs
docker logs ai-mesh-collab-chat -f --tail 50

# Health check
curl http://localhost:8130/health

# Model performance stats
curl http://localhost:8130/api/model-stats

# Run all tests (integration tests against running container)
cd /data/ai-mesh && pytest collab-chat/tests/ -v

# Run a single test
pytest collab-chat/tests/test_roundtable.py::test_health_endpoint -v
```

No build step. No linting configured. Tests use httpx against `http://localhost:8130` (container must be running). Test fixtures in `tests/conftest.py` provide an `httpx.Client`.

## Architecture

```
Browser (index.html) <--WebSocket /ws--> main.py <--HTTP POST--> AI Router (:8110)
                                            |                         |
                                       JSON file storage      routes to AI proxies
                                  (tasks, projects, decisions) (Claude, GPT, Grok, etc.)
```

### Participant System

Two types: `"model"` (raw AI, no persona) and `"agent"` (model + system prompt persona). Multiple agents can share the same underlying model ID (e.g., CEO, CFO, and Accountant all use `qwen2.5:latest`). Loaded from `participants.json` at startup; falls back to `DEFAULT_PARTICIPANTS` in `main.py`. Dynamic personas from `personas.json` are appended at startup.

Cost strategy: local/free models (qwen2.5, dolphin-llama3, nous-hermes2, dolphin-mistral) for research/analysis; cloud models for high-stakes decisions.

### Roundtable Flow (`run_roundtable`)

1. **Input handling**: Sanitize input, detect `@mentions` for directed discussion
2. **Short-circuit**: Single participant or simple messages skip deliberation
3. **Round 1**: All active participants respond in parallel via `run_parallel_round()`, gated by `MODEL_SEMAPHORE` (default 8 concurrent)
4. **Rounds 2+**: Sequential debate — each participant sees prior responses, challenges/supports/counters. Continues until convergence (60%+ say "CONVERGED") or `max_deliberation_rounds` cap
5. **Synthesis**: First active participant's model produces a final combined answer

### Concurrency Model

- `MODEL_SEMAPHORE` (default 8) — gates concurrent HTTP calls to the router
- `SESSION_LOCK` — ensures only one roundtable/research job runs at a time; `run_serialized_job()` wraps all async workflows with this lock
- `deliberation_state` dict — tracks active/paused/stop_requested for mid-deliberation control

### Preset System

Two layers of presets exist (known duplication):
- `PRESETS` dict in `main.py` (~line 568) — hardcoded presets activated via WebSocket `activate_preset` messages, matched by participant display name
- `presets.json` — file-based presets served via `GET /api/presets`, includes team presets (`is_team: true`) for coding/execution teams

### Data Persistence (JSON files, not DB)

| File | Store variable | Purpose |
|------|---------------|---------|
| `participants.json` | `ALL_PARTICIPANTS` | Participant definitions |
| `model_config.json` | `MODEL_CONFIG` | Per-model max_tokens/temperature/timeout |
| `personas.json` | (appended to `ALL_PARTICIPANTS`) | Dynamically researched personas |
| `presets.json` | (loaded on demand) | Team + discussion presets |
| `tasks_data.json` | `TASK_STORE` | Task board state |
| `projects.json` | `PROJECT_STORE` | Project registry |
| `decisions.json` | `DECISION_STORE` | Decision history |

All use `_load_json_file()` / `_save_json_file()` helpers with atomic writes.

### Global State

Key in-memory state beyond the JSON stores:

- `conversation_history` — list of message dicts, trimmed at `MAX_CONVERSATION_HISTORY` (200)
- `connected_clients` — list of active WebSocket connections
- `TRACKED_JOBS` — dict tracking in-flight CrewAI jobs, polled every 15s by `poll_tracked_jobs()`
- `ACTIVE_PROJECT` — dict with `code` key for the currently active project
- `MODEL_STATS` — per-model latency/error/call statistics

## REST API Endpoints

### Core
- `GET /` — Serve frontend HTML
- `GET /health` — Health check (uptime, participant count, model stats)
- `GET /api/model-stats` — Per-model latency, error rate, call count
- `GET /api/minutes` — Meeting minutes / conversation export
- `POST /api/clear` — Clear conversation history
- `GET /api/participants` — List all participants with enabled status
- `PUT /api/participants/{name}` — Update participant (enable/disable)
- `GET /api/presets` — List available roundtable presets

### Edit Workflow
- `POST /api/propose-edit` — Propose a code/config edit (returns edit_id)
- `POST /api/approve-edit/{edit_id}` — Approve and apply a proposed edit
- `POST /api/reject-edit/{edit_id}` — Reject a proposed edit
- `GET /api/pending-edits` — List all pending edit proposals

### Roundtable Sessions
- `POST /api/roundtable/start` — Start a structured session with preset
- `GET /api/roundtable/status` — Current session state
- `POST /api/roundtable/vote` — Record participant vote per round
- `GET /api/export/{format}` — Export conversation as JSON/Markdown/CSV

### Task Board
- `GET /api/tasks` — List tasks (query: project, status, team, assignee)
- `POST /api/tasks` — Create a new task
- `GET /api/tasks/board` — Kanban board view (tasks grouped by status)
- `GET /api/tasks/{task_id}` — Get task details
- `PUT /api/tasks/{task_id}` — Update task (status, assignee, result, notes)
- `DELETE /api/tasks/{task_id}` — Delete a task
- `POST /api/tasks/{task_id}/discuss` — Assemble team and start roundtable about a task

### Projects, Jobs, Decisions, Dashboard
- `GET /api/projects` — List all registered projects
- `GET /api/projects/{code}` — Project details with task summary
- `POST /api/projects` — Register a new project
- `PUT /api/projects/{code}` — Update project config
- `POST /api/jobs/trigger` — Trigger a CrewAI agent job
- `GET /api/jobs` — List all jobs (query: project, status)
- `GET /api/jobs/{job_id}` — Get job status and result
- `GET /api/decisions` — Recent decisions with outcomes
- `POST /api/decisions` — Record a decision manually
- `GET /api/dashboard` — Combined dashboard: tasks, jobs, P&L, decisions
- `GET /api/pnl` — P&L from PostgreSQL `ai_mesh.budget_ledger` (if DB available)

## WebSocket Protocol

**Client -> Server**: `message`, `stop`, `pause`, `resume`, `toggle`, `activate_preset`, `set_max_rounds`, `directed`, `crosstalk`, `research_persona`, `remove_persona`, `suggest_model`, `dev_bar_message`, `dev_bar_apply`, `dev_bar_clear`, `create_task`, `update_task`, `list_tasks`, `trigger_job`, `approve_decision`, `reject_decision`, `set_project`

**Server -> Client**: `message`, `thinking`, `round_separator`, `deliberation_start/end/stopped/paused/resumed`, `deliberation_state`, `participants`, `settings`, `presets`, `status`, `task_created`, `task_updated`, `tasks_list`, `job_started`, `job_update`, `job_error`, `decision_detected`, `decision_executing`, `decision_rejected`, `team_assembled`, `system`, `model_suggestion`, `dev_bar_cleared`

Full schemas in `contracts.py`.

## Multi-Agent Coordination

`contracts.py` defines shared contracts for multi-agent parallel development (Claude Code, Codex, OpenCode working in separate worktrees). It includes WebSocket/REST schemas, task/project/decision schemas, team presets (`CDL_VAULT_TEAMS`), and `FILE_OWNERSHIP` rules. **Do not modify unilaterally** — coordinate changes across worktrees.

`TASKS.md` tracks the Phase 1 task board for the multi-agent effort.

## Key Function Map

| Function | Purpose |
|----------|---------|
| `ask_model()` | HTTP POST to router with retries (3 attempts, exponential backoff), updates `MODEL_STATS` |
| `run_roundtable()` | Main entry: mention detection, parallel rounds, debate rounds, synthesis |
| `run_parallel_round()` | Fans out `ask_model()` calls concurrently for a round |
| `run_directed_discussion()` | @mention-based conversation with specific participants |
| `run_cross_talk()` | Inter-participant debate round |
| `build_messages()` | Constructs message arrays with persona system prompts and trimmed history |
| `websocket_endpoint()` | Central WebSocket handler — dispatches all client message types |
| `assemble_team_for_task()` | Enables participants matching a team preset for task discussions |
| `handle_research_persona()` | Researches real people and creates agent personas dynamically |
| `handle_dev_bar_message/apply()` | Dev bar code/config editing workflow with backup creation |
| `poll_tracked_jobs()` | Background task polling CrewAI job status every 15s |
| `create_task_obj()` | Creates a task dict conforming to `TASK_SCHEMA` |
| `recompute_blocked()` | When a task completes, unblocks dependent tasks |
| `run_serialized_job()` | Wraps async workflows with `SESSION_LOCK` for serial execution |

## Important Patterns

- All model calls go through the AI Router at `ROUTER_URL` (default `http://ai-mesh-router:8000`), never directly to providers.
- Conversation history trimmed at `MAX_CONVERSATION_HISTORY` (200 messages). Per-round history limits vary by context (30 for rounds, 40 for synthesis, 16 for directed, 10 for dev bar).
- Backups are created automatically before edits in `backups/` with a manifest file. Changes logged in `edit_log.md`.
- The `companies/` directory (sibling to collab-chat) contains per-company roundtable configurations for the multi-company holding structure.
- `structured_session` dict tracks formal roundtable sessions started via `POST /api/roundtable/start` (separate from ad-hoc WebSocket chat).
- Environment variables: `ROUTER_URL`, `CLAUDE_CODE_URL`, `CREWAI_URL`, `MODEL_CONCURRENCY`, `COMPANY_CODE`, `COMPANY_CONFIG_DIR`.

## Tech Stack

Python 3.12, FastAPI, uvicorn, httpx, websockets, Pydantic v2. No ORM — JSON file storage. Dependencies in `requirements.txt` (4 packages). Single-file backend and single-file frontend.
