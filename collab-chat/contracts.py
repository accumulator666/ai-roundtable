"""
API & Message Contracts for AI Roundtable — Phase 1: AI Company Platform
=========================================================================
Shared interface definitions between frontend and backend.
All agents (Claude Code, Codex, OpenCode) MUST conform to these contracts.

DO NOT modify this file unilaterally — coordinate changes across all worktrees.

Phase 1 additions:
  - Task board system (create, assign, track, complete)
  - CrewAI job integration (trigger from roundtable, track status)
  - Company dashboard (P&L, decisions, jobs)
  - Project management (CDL-Vault as first project)
  - Team presets for multi-language coding
"""

from typing import Any, Literal

# ============================================================
# WebSocket Message Types (client <-> server)
# ============================================================

# Client -> Server
WS_CLIENT_MESSAGES = {
    # --- Existing (unchanged) ---
    "chat": {
        "type": "chat",
        "message": str,
        "preset": str | None,
    },
    "stop": {"type": "stop"},
    "pause": {"type": "pause"},
    "directed": {
        "type": "directed",
        "message": str,
        "participant_id": str,
    },

    # --- CrewAI Job Integration ---
    "trigger_job": {
        "type": "trigger_job",
        "job_type": str,              # "strategy-session" | "build-business" | "market-research"
        "project": str | None,        # Project code (e.g., "cdl-vault")
        "params": dict | None,        # Job-specific params (business_description, target_audience, etc.)
    },
    "approve_decision": {
        "type": "approve_decision",
        "decision_id": str,
    },
    "reject_decision": {
        "type": "reject_decision",
        "decision_id": str,
    },

    # --- Task Board ---
    "create_task": {
        "type": "create_task",
        "title": str,
        "description": str,
        "project": str,               # Project code (e.g., "cdl-vault")
        "team": str | None,           # Team preset to assign (e.g., "backend-team", "mobile-team")
        "assignee": str | None,       # Specific participant name
        "priority": str,              # "critical" | "high" | "medium" | "low"
        "language": str | None,       # Primary language: "python" | "swift" | "kotlin" | "typescript" | "rust" | None
        "depends_on": list[str],      # Task IDs this depends on
        "integration_notes": str | None,  # Notes for how this integrates with other tasks
    },
    "update_task": {
        "type": "update_task",
        "task_id": str,
        "status": str | None,         # "backlog" | "assigned" | "in_progress" | "review" | "done" | "blocked"
        "assignee": str | None,
        "result": str | None,         # Completion summary or deliverable
        "integration_notes": str | None,
    },
    "list_tasks": {
        "type": "list_tasks",
        "project": str | None,        # Filter by project
        "status": str | None,         # Filter by status
        "team": str | None,           # Filter by team
    },

    # --- Project Management ---
    "set_project": {
        "type": "set_project",
        "project": str,               # Project code to make active
    },
}

# Server -> Client
WS_SERVER_MESSAGES = {
    # --- Existing (unchanged) ---
    "response": {
        "type": "response",
        "participant": str,
        "participant_id": str,
        "color": str,
        "content": str,
        "round": int,
        "is_synthesis": bool,
    },
    "stream": {
        "type": "stream",
        "participant": str,
        "participant_id": str,
        "color": str,
        "token": str,
        "round": int,
        "done": bool,
    },
    "status": {
        "type": "status",
        "message": str,
        "phase": str,
        "round": int | None,
        "metadata": dict | None,
    },
    "system": {
        "type": "system",
        "event": str,
        "data": dict,
    },

    # --- CrewAI Job Lifecycle ---
    "job_started": {
        "type": "job_started",
        "job_id": str,
        "job_type": str,
        "description": str,
        "project": str | None,
    },
    "job_update": {
        "type": "job_update",
        "job_id": str,
        "status": str,            # "queued" | "running" | "completed" | "failed"
        "result": str | None,
        "progress": int | None,   # 0-100 percentage if available
    },
    "job_error": {
        "type": "job_error",
        "job_id": str,
        "error": str,
    },

    # --- Decision Detection ---
    "decision_detected": {
        "type": "decision_detected",
        "decision_id": str,
        "action": str,
        "description": str,
        "project": str | None,
    },
    "decision_executing": {
        "type": "decision_executing",
        "decision_id": str,
    },
    "decision_rejected": {
        "type": "decision_rejected",
        "decision_id": str,
    },

    # --- Task Board Updates ---
    "task_created": {
        "type": "task_created",
        "task": dict,             # Full task object (see TASK_SCHEMA)
    },
    "task_updated": {
        "type": "task_updated",
        "task": dict,             # Updated task object
    },
    "tasks_list": {
        "type": "tasks_list",
        "tasks": list[dict],      # List of task objects
        "project": str | None,
    },

    # --- Team Assembly ---
    "team_assembled": {
        "type": "team_assembled",
        "project": str,
        "team": str,              # Team preset name
        "members": list[str],     # Participant names activated
    },
}

# ============================================================
# REST API Endpoints
# ============================================================

REST_ENDPOINTS = {
    # --- Existing (unchanged) ---
    "GET /":                    "Serve the frontend HTML",
    "GET /health":              "Health check with uptime, participant count, model stats",
    "GET /api/model-stats":     "Per-model latency, error rate, call count",
    "GET /api/minutes":         "Meeting minutes / conversation export",
    "POST /api/clear":          "Clear conversation history",

    # --- Edit workflow (existing) ---
    "POST /api/propose-edit":              "Propose a code/config edit (returns edit_id)",
    "POST /api/approve-edit/{edit_id}":    "Approve and apply a proposed edit",
    "POST /api/reject-edit/{edit_id}":     "Reject a proposed edit",
    "GET /api/pending-edits":              "List all pending edit proposals",

    # --- Participant & preset management (existing) ---
    "GET /api/participants":               "List all participants with enabled status",
    "PUT /api/participants/{name}":        "Update participant (enable/disable)",
    "GET /api/presets":                    "List available roundtable presets",

    # --- Roundtable session (existing) ---
    "POST /api/roundtable/start":          "Start a structured session with preset",
    "GET /api/roundtable/status":          "Current session state",
    "POST /api/roundtable/vote":           "Record participant vote per round",
    "GET /api/export/{format}":            "Export conversation as JSON/Markdown/CSV",

    # === PHASE 1 NEW ENDPOINTS ===

    # --- Task Board ---
    "GET /api/tasks":                      "List tasks (query: project, status, team, assignee)",
    "POST /api/tasks":                     "Create a new task",
    "GET /api/tasks/{task_id}":            "Get task details",
    "PUT /api/tasks/{task_id}":            "Update task (status, assignee, result, notes)",
    "DELETE /api/tasks/{task_id}":         "Delete a task",
    "POST /api/tasks/{task_id}/discuss":   "Start roundtable discussion about a specific task",
    "GET /api/tasks/board":                "Get kanban board view (tasks grouped by status)",

    # --- Project Management ---
    "GET /api/projects":                   "List all registered projects",
    "GET /api/projects/{code}":            "Get project details (tasks, team, status)",
    "POST /api/projects":                  "Register a new project",
    "PUT /api/projects/{code}":            "Update project config",

    # --- CrewAI Job Integration ---
    "POST /api/jobs/trigger":              "Trigger a CrewAI agent job",
    "GET /api/jobs":                       "List all jobs (query: project, status)",
    "GET /api/jobs/{job_id}":              "Get job status and result",

    # --- Company Dashboard ---
    "GET /api/dashboard":                  "Combined dashboard: tasks, jobs, P&L, decisions",
    "GET /api/pnl":                        "P&L from budget_ledger",
    "GET /api/decisions":                  "Recent decisions with outcomes",
    "POST /api/decisions":                 "Record a decision manually",
}

# ============================================================
# Task Schema
# ============================================================

TASK_SCHEMA = {
    "task_id": str,               # UUID hex (8 chars)
    "title": str,                 # Short task title
    "description": str,           # Detailed task description
    "project": str,               # Project code (e.g., "cdl-vault")
    "status": str,                # "backlog" | "assigned" | "in_progress" | "review" | "done" | "blocked"
    "priority": str,              # "critical" | "high" | "medium" | "low"
    "team": str | None,           # Team preset assigned (e.g., "backend-team")
    "assignee": str | None,       # Specific participant name
    "language": str | None,       # Primary language for coding tasks
    "depends_on": list[str],      # Task IDs this depends on
    "blocked_by": list[str],      # Task IDs currently blocking this (computed from depends_on + status)
    "integration_notes": str | None,  # How this connects to other tasks
    "result": str | None,         # Completion deliverable or summary
    "created_at": str,            # ISO datetime
    "updated_at": str,            # ISO datetime
    "job_id": str | None,         # Linked CrewAI job ID if execution was triggered
}

TASK_STATUSES = ["backlog", "assigned", "in_progress", "review", "done", "blocked"]
TASK_PRIORITIES = ["critical", "high", "medium", "low"]

# ============================================================
# Project Schema
# ============================================================

PROJECT_SCHEMA = {
    "code": str,                  # Short code (e.g., "cdl-vault")
    "name": str,                  # Display name (e.g., "CDL Vault")
    "description": str,           # What this project is
    "repo_path": str | None,      # Filesystem path (e.g., "/data/cdl-vault")
    "tech_stack": list[str],      # Languages/frameworks (e.g., ["python", "fastapi", "nextjs", "typescript"])
    "teams": list[str],           # Team presets applicable to this project
    "active": bool,               # Whether this is the currently active project
    "created_at": str,            # ISO datetime
}

# ============================================================
# Decision Schema (for persistence)
# ============================================================

DECISION_SCHEMA = {
    "decision_id": str,
    "project": str | None,
    "description": str,           # What was decided
    "action": str | None,         # Triggered action (job type or manual)
    "outcome": str | None,        # Result of execution
    "decided_by": list[str],      # Participants who contributed
    "approved_by": str | None,    # Who approved (user or auto)
    "created_at": str,
    "status": str,                # "proposed" | "approved" | "rejected" | "executed" | "failed"
}

# ============================================================
# Participant Schema (unchanged)
# ============================================================

PARTICIPANT_SCHEMA = {
    "id": str,                    # Model ID used for routing (e.g., "gpt-5.2")
    "name": str,                  # Display name (e.g., "CEO", "GPT-5.2")
    "color": str,                 # Hex color (e.g., "#22c55e")
    "type": Literal["model", "agent"],
    "persona": str | None,
    "enabled": bool,
}

# ============================================================
# Preset Schema (extended with team presets)
# ============================================================

PRESET_SCHEMA = {
    "name": str,                  # Preset display name
    "description": str,           # What this preset is for
    "participants": list[str],    # List of participant names to enable
    "deliberation_rounds": int,
    "synthesis_model": str,
    "is_team": bool,              # True = coding/execution team, False = discussion preset
}

# ============================================================
# Team Presets for CDL-Vault (defined here, loaded by OpenCode into presets.json)
# ============================================================

# These are the coding/execution team definitions.
# OpenCode creates the actual presets.json entries.
# Codex renders team selector UI.
# Claude Code implements the backend team-assembly logic.

CDL_VAULT_TEAMS = {
    "backend-team": {
        "description": "Python/FastAPI backend development",
        "language": "python",
        "members": ["Tech Lead", "Backend Dev", "Database Architect", "Security Engineer", "QA Engineer"],
    },
    "frontend-team": {
        "description": "Next.js/TypeScript frontend development",
        "language": "typescript",
        "members": ["Tech Lead", "Frontend Dev", "UI/UX Designer", "UX Psychologist", "QA Engineer"],
    },
    "mobile-team": {
        "description": "iOS (Swift) + Android (Kotlin) mobile apps",
        "language": "swift,kotlin",
        "members": ["Tech Lead", "Mobile Dev", "iOS Dev", "Android Dev", "UI/UX Designer", "QA Engineer"],
    },
    "devops-team": {
        "description": "Infrastructure, deployment, CI/CD",
        "language": None,
        "members": ["Tech Lead", "DevOps", "Security Engineer", "Database Architect"],
    },
    "sales-team": {
        "description": "Sales strategy, funnels, outreach",
        "language": None,
        "members": ["Sales Director", "Copywriter", "SEO Specialist", "Persuasion Expert", "Market Researcher"],
    },
    "marketing-team": {
        "description": "Content, social media, brand",
        "language": None,
        "members": ["Creative Director", "Copywriter", "Social Media", "SEO Specialist", "UX Psychologist"],
    },
    "finance-team": {
        "description": "Budget, pricing, P&L, compliance",
        "language": None,
        "members": ["CFO", "Accountant", "Tax Strategist", "Risk Manager", "Compliance"],
    },
    "qa-team": {
        "description": "Testing, quality assurance, security audit",
        "language": None,
        "members": ["QA Engineer", "QA Tester", "Security Engineer", "DevOps"],
    },
    "leadership": {
        "description": "Executive review — all teams report here",
        "language": None,
        "members": ["CEO", "CTO", "CFO", "COO", "Chief of Staff", "Project Planner"],
    },
    "full-company": {
        "description": "All hands — entire company for major milestones",
        "language": None,
        "members": ["CEO", "CTO", "CFO", "COO", "Chief of Staff", "Tech Lead", "Backend Dev",
                     "Frontend Dev", "Mobile Dev", "DevOps", "Sales Director", "Copywriter",
                     "Market Researcher", "QA Engineer", "Risk Manager", "Devil's Advocate"],
    },
}

# ============================================================
# File Ownership (which agent owns which files)
# ============================================================

FILE_OWNERSHIP = {
    "claude-code": [
        "collab-chat/main.py",           # Backend logic, WebSocket, API endpoints
        "collab-chat/contracts.py",       # Shared contracts (coordinate changes)
    ],
    "codex": [
        "collab-chat/index.html",         # Frontend UI, JS, CSS
    ],
    "opencode": [
        "collab-chat/participants.json",  # Participant definitions
        "collab-chat/model_config.json",  # Model tuning
        "collab-chat/presets.json",       # Roundtable presets (team + discussion)
        "collab-chat/projects.json",      # Project registry (NEW)
        "tests/test_roundtable.py",       # Integration tests
        "tests/test_tasks.py",            # Task board tests (NEW)
        "tests/test_jobs.py",             # Job integration tests (NEW)
    ],
}
