# Multi-Agent Task Board — Phase 1: AI Company Platform

Coordination file for Claude Code, Codex, and OpenCode working in parallel.

**Contracts:** `contracts.py` — All agents must conform to these interfaces.
**Merge target:** `main` branch

**Goal:** Transform collab-chat from a discussion-only roundtable into an AI company platform that can assign work, execute tasks, track jobs, and manage projects like a Fortune 500 team building CDL-Vault.

---

## Claude Code — Backend (`main.py`, `contracts.py`)

Working directory: `/data/ai-mesh/.worktrees/claude-work/collab-chat/`

### Task Board System
- [ ] Add in-memory task store (`TASKS: dict[str, dict]`) with persistence to `tasks_data.json`
- [ ] Add `POST /api/tasks` — create task (fields from `TASK_SCHEMA` in contracts.py)
- [ ] Add `GET /api/tasks` — list tasks with query filters (project, status, team, assignee)
- [ ] Add `GET /api/tasks/{task_id}` — get single task details
- [ ] Add `PUT /api/tasks/{task_id}` — update task status, assignee, result, integration_notes
- [ ] Add `DELETE /api/tasks/{task_id}` — remove a task
- [ ] Add `GET /api/tasks/board` — return tasks grouped by status (kanban view)
- [ ] Add `POST /api/tasks/{task_id}/discuss` — assemble the task's team and start a roundtable about that task
- [ ] Add dependency tracking: when a task completes, unblock dependent tasks
- [ ] Add WebSocket handlers: `create_task`, `update_task`, `list_tasks` message types
- [ ] Broadcast `task_created` and `task_updated` to all clients on changes

### Project Management
- [ ] Add project registry store with persistence to `projects.json` (OpenCode creates seed data)
- [ ] Add `GET /api/projects` — list all projects
- [ ] Add `GET /api/projects/{code}` — project details with task summary counts
- [ ] Add `POST /api/projects` — register a new project
- [ ] Add `PUT /api/projects/{code}` — update project config
- [ ] Add WebSocket handler: `set_project` — switch active project context
- [ ] Load `projects.json` at startup, seed CDL-Vault as default project if empty

### CrewAI Job Integration
- [ ] Add `POST /api/jobs/trigger` — POST to CrewAI at `http://ai-mesh-crewai:8000/v1/agents/{job_type}`
- [ ] Add `GET /api/jobs` — proxy to CrewAI `GET /v1/agents/jobs` with optional project filter
- [ ] Add `GET /api/jobs/{job_id}` — proxy to CrewAI `GET /v1/agents/jobs/{job_id}`
- [ ] Add WebSocket handler: `trigger_job` — trigger job and broadcast `job_started`
- [ ] Add background job poller: check running jobs every 15s, broadcast `job_update` on status change
- [ ] Link jobs to tasks: when a job completes, update the linked task's status and result

### Decision Tracking
- [ ] Add decision store with persistence to `decisions.json`
- [ ] Add `GET /api/decisions` — list recent decisions
- [ ] Add `POST /api/decisions` — record a decision manually
- [ ] Add WebSocket handlers: `approve_decision`, `reject_decision`
- [ ] After synthesis round, scan for actionable decisions and broadcast `decision_detected`

### Dashboard
- [ ] Add `GET /api/dashboard` — combined view: active project, task counts by status, running jobs, recent decisions
- [ ] Add `GET /api/pnl` — query PostgreSQL `ai_mesh.budget_ledger` for P&L summary (if DB available, else return empty)

### Team Assembly
- [ ] Add team assembly logic: when a task is created with a `team` field, enable those participants
- [ ] Broadcast `team_assembled` when a team preset is activated for a task
- [ ] Support `POST /api/tasks/{task_id}/discuss` to auto-assemble team and start discussion

### Rules
- Only modify: `main.py`, `contracts.py`
- Conform to schemas in `contracts.py`
- Keep ALL existing endpoints and WebSocket handlers working (don't break anything)
- Persist task/project/decision data to JSON files (not DB — keep it simple for Phase 1)
- CrewAI URL: `http://ai-mesh-crewai:8000` (same Docker network)

---

## Codex — Frontend (`index.html`)

Working directory: `/data/ai-mesh/.worktrees/codex-work/collab-chat/`

### Task Board UI
- [ ] Add "Tasks" tab/panel in the sidebar (alongside existing participant list)
- [ ] Build kanban board view: columns for backlog, assigned, in_progress, review, done, blocked
- [ ] Each task card shows: title, priority badge, assignee, language tag, team tag
- [ ] Task card click expands to show: description, integration notes, dependencies, linked job
- [ ] "New Task" button opens a form: title, description, project, team selector, priority, language, depends_on
- [ ] Task status drag-and-drop between columns (calls `PUT /api/tasks/{task_id}`)
- [ ] "Discuss" button on each task card (calls `POST /api/tasks/{task_id}/discuss`)

### Project Selector
- [ ] Add project dropdown at top of sidebar (calls `GET /api/projects`)
- [ ] Switching project filters the task board and sets context for new tasks
- [ ] Show project name and tech stack badges next to dropdown

### Job Status Panel
- [ ] Add "Jobs" section below task board showing running/recent CrewAI jobs
- [ ] Each job shows: type, status indicator (spinner/check/x), project, linked task
- [ ] "Trigger Job" button with job type selector (strategy-session, build-business, market-research)
- [ ] Poll `GET /api/jobs` every 15s to update status (or use WebSocket `job_update` messages)

### Dashboard View
- [ ] Add "Dashboard" tab showing summary cards:
  - Task counts by status (backlog: N, in_progress: N, done: N, etc.)
  - Active jobs count
  - Recent decisions list
- [ ] Dashboard calls `GET /api/dashboard` on load

### Team Assembly UI
- [ ] When creating a task, team selector dropdown shows team presets from `CDL_VAULT_TEAMS`
- [ ] Selecting a team auto-fills members list and shows which participants will be activated
- [ ] "Assemble Team" button that activates a team preset for ad-hoc discussions

### Integration Notes Display
- [ ] On task cards in "review" or "done" status, show integration_notes prominently
- [ ] Visual connector lines or badges showing task dependencies

### Rules
- Only modify: `index.html`
- Read `contracts.py` for API shapes — do not invent new endpoints
- Use existing CSS variables and color scheme
- All API calls go to relative paths (no hardcoded hosts)
- Keep ALL existing UI working (chat, presets, participants, dev bar)
- New panels should be togglable — don't clutter the main chat view

---

## OpenCode — Config, Data, & Tests

Working directory: `/data/ai-mesh/.worktrees/opencode-work/collab-chat/`

### New Participants
- [ ] Add to `participants.json` — new platform-specific coding agents:
  - "iOS Dev" — `claude-sonnet-4-5` model, Swift/SwiftUI/Xcode expertise persona
  - "Android Dev" — `qwen2.5-coder:7b` model, Kotlin/Jetpack Compose persona
  - "Rust Dev" — `qwen2.5-coder:7b` model, Rust systems programming persona
  - "Python Lead" — `claude-sonnet-4-5` model, Python/FastAPI senior lead persona (distinct from generic Backend Dev)
  - "TypeScript Lead" — `qwen2.5-coder:7b` model, TypeScript/Next.js/React senior lead persona (distinct from generic Frontend Dev)
  - "Integration Engineer" — `nous-hermes2:latest` model, specialist in connecting components, API contracts, data flow between teams
  - "Technical Writer" — `dolphin-llama3:8b` model, documentation, API docs, code comments, README files
- [ ] All new participants: `"enabled": false` by default, `"type": "agent"` with detailed personas
- [ ] Ensure every participant `id` exists in the router's `MODEL_TO_PROXY` or Ollama model list

### New Team Presets
- [ ] Add to `presets.json` — team presets matching `CDL_VAULT_TEAMS` in contracts.py:
  - `backend-team`: Tech Lead, Backend Dev, Python Lead, Database Architect, Security Engineer, QA Engineer
  - `frontend-team`: Tech Lead, Frontend Dev, TypeScript Lead, UI/UX Designer, UX Psychologist, QA Engineer
  - `mobile-team`: Tech Lead, Mobile Dev, iOS Dev, Android Dev, UI/UX Designer, QA Engineer
  - `devops-team`: Tech Lead, DevOps, Security Engineer, Database Architect
  - `sales-team`: Sales Director, Copywriter, SEO Specialist, Persuasion Expert, Market Researcher
  - `marketing-team`: Creative Director, Copywriter, Social Media, SEO Specialist, UX Psychologist
  - `finance-team`: CFO, Accountant, Tax Strategist, Risk Manager, Compliance
  - `qa-team`: QA Engineer, QA Tester, Security Engineer, DevOps
  - `leadership`: CEO, CTO, CFO, COO, Chief of Staff, Project Planner
  - `full-company`: All key roles (16 participants) for major milestone reviews
- [ ] Each preset: `"is_team": true`, appropriate `deliberation_rounds` (teams: 1-2, leadership: 2-3)
- [ ] Keep ALL existing presets (quick-3, full-panel, debate, research, finance-review)

### CDL-Vault Project Config
- [ ] Create `projects.json` with CDL-Vault as the seed project:
  ```json
  {
    "cdl-vault": {
      "code": "cdl-vault",
      "name": "CDL Vault",
      "description": "Fair reputation scoring SaaS for CDL truck drivers",
      "repo_path": "/data/cdl-vault",
      "tech_stack": ["python", "fastapi", "nextjs", "typescript", "postgresql", "redis"],
      "teams": ["backend-team", "frontend-team", "mobile-team", "devops-team", "sales-team", "marketing-team", "finance-team", "qa-team", "leadership"],
      "active": true,
      "created_at": "2026-03-05T00:00:00Z"
    }
  }
  ```

### Model Config Updates
- [ ] Add to `model_config.json` — entries for any new models used by new participants
- [ ] Ensure `claude-sonnet-4-5` has appropriate timeout for iOS Dev and Python Lead roles

### Tests — Task Board
- [ ] Create `tests/test_tasks.py`:
  - Test `POST /api/tasks` — create a task, verify response matches TASK_SCHEMA
  - Test `GET /api/tasks` — list tasks, filter by project
  - Test `GET /api/tasks` — filter by status and team
  - Test `PUT /api/tasks/{task_id}` — update status from "backlog" to "in_progress"
  - Test `PUT /api/tasks/{task_id}` — update with result when completing
  - Test `DELETE /api/tasks/{task_id}` — remove task
  - Test `GET /api/tasks/board` — verify kanban grouping
  - Test dependency tracking — completing task A unblocks task B

### Tests — Job Integration
- [ ] Create `tests/test_jobs.py`:
  - Test `POST /api/jobs/trigger` — trigger a job (mock CrewAI response)
  - Test `GET /api/jobs` — list jobs
  - Test `GET /api/jobs/{job_id}` — get job status

### Tests — Projects & Dashboard
- [ ] Add to `tests/test_roundtable.py` (or new file):
  - Test `GET /api/projects` — returns CDL-Vault
  - Test `GET /api/projects/cdl-vault` — returns project details
  - Test `GET /api/dashboard` — returns combined dashboard data
  - Test `GET /api/decisions` — returns empty or seeded decisions

### Rules
- Only modify: `participants.json`, `model_config.json`, `presets.json`, `projects.json` (NEW), `tests/*`
- Read `contracts.py` for schemas
- Participant IDs must exist in router's `MODEL_TO_PROXY` or Ollama
- Test against `http://localhost:8130` (or mock for unit tests)
- Do NOT modify `main.py` or `index.html`

---

## Merge Order

1. **OpenCode first** — config + data files + tests (no code conflicts, establishes test expectations)
2. **Claude Code second** — backend (new endpoints, WebSocket handlers, data stores)
3. **Codex last** — frontend (depends on backend endpoints existing to call)

---

## Status Key

- `[ ]` = Not started
- `[~]` = In progress
- `[x]` = Complete
- `[!]` = Blocked

---

## Architecture Notes

### Data Flow: User → Task → Team → Execution → Integration
```
1. User creates task in UI           → POST /api/tasks
2. Task assigned to a team           → team preset activates participants
3. Team discusses via roundtable     → POST /api/tasks/{id}/discuss
4. Decision made → job triggered     → POST /api/jobs/trigger → CrewAI
5. Job completes → task updated      → PUT /api/tasks/{id} status=done
6. Dependent tasks unblocked         → blocked tasks move to "assigned"
7. All tasks done → leadership       → full-company review meeting
```

### Storage (Phase 1 — JSON files, Phase 2 will use PostgreSQL)
- `tasks_data.json` — Task board state (Claude Code creates/manages)
- `projects.json` — Project registry (OpenCode creates seed, Claude Code loads)
- `decisions.json` — Decision history (Claude Code creates/manages)
- `participants.json` — Participant definitions (OpenCode owns)
- `presets.json` — Team + discussion presets (OpenCode owns)

### CrewAI Integration
- URL: `http://ai-mesh-crewai:8000`
- Trigger: `POST /v1/agents/{job_type}` with JSON body
- Poll: `GET /v1/agents/jobs/{job_id}` every 15s
- Job types: `strategy-session`, `build-business`
