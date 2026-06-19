"""
Database layer for AI Corporate Empire.
Auto-creates all tables on first connect — no manual init needed.
All queries are company-scoped via company_id.
"""

import os
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger("db")

# Connection settings from environment
DB_HOST = os.environ.get("POSTGRES_HOST", "prompt-template-db")
DB_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
DB_NAME = os.environ.get("POSTGRES_DB", "ai_mesh")
DB_USER = os.environ.get("POSTGRES_USER", "admin")
DB_PASS = os.environ.get("POSTGRES_PASSWORD", "")

_pool: Optional[asyncpg.Pool] = None


# ============================================================
# Schema — auto-created on startup
# ============================================================

SCHEMA_SQL = """
-- Company registry
CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    code TEXT UNIQUE NOT NULL,
    description TEXT,
    port INTEGER,
    budget_allocated NUMERIC(12,2) DEFAULT 0,
    budget_spent NUMERIC(12,2) DEFAULT 0,
    total_revenue NUMERIC(12,2) DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

-- Influencer profiles (MeshMedia)
CREATE TABLE IF NOT EXISTS influencers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    persona JSONB NOT NULL DEFAULT '{}',
    profile_image_url TEXT,
    account_credentials JSONB DEFAULT '{}',
    follower_count INTEGER DEFAULT 0,
    total_revenue NUMERIC(12,2) DEFAULT 0,
    status TEXT DEFAULT 'setup',
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

-- Content pipeline (MeshMedia)
CREATE TABLE IF NOT EXISTS content_pipeline (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    influencer_id UUID REFERENCES influencers(id),
    content_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    script TEXT,
    media_urls JSONB DEFAULT '[]',
    status TEXT DEFAULT 'draft',
    scheduled_at TIMESTAMP,
    published_at TIMESTAMP,
    engagement JSONB DEFAULT '{}',
    revenue NUMERIC(10,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Investment portfolio (MeshCapital)
CREATE TABLE IF NOT EXISTS portfolio (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    asset_type TEXT NOT NULL,
    ticker TEXT,
    quantity NUMERIC(16,6),
    entry_price NUMERIC(12,4),
    current_price NUMERIC(12,4),
    pnl NUMERIC(12,2) DEFAULT 0,
    status TEXT DEFAULT 'open',
    source TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

-- Cross-company capital transfers
CREATE TABLE IF NOT EXISTS capital_transfers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_company UUID REFERENCES companies(id),
    to_company UUID REFERENCES companies(id),
    amount NUMERIC(12,2) NOT NULL,
    reason TEXT,
    approved_by TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Extend existing tables with company_id (safe — ADD IF NOT EXISTS)
DO $$ BEGIN
    ALTER TABLE budget_ledger ADD COLUMN company_id UUID REFERENCES companies(id);
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE decisions ADD COLUMN company_id UUID REFERENCES companies(id);
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE agent_tasks ADD COLUMN company_id UUID REFERENCES companies(id);
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

-- Projects (CEO pitch → outline → execution → integration)
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    pitch TEXT NOT NULL,
    outline JSONB DEFAULT '{}',
    status TEXT DEFAULT 'planned',
    synthesis TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Project tasks (assigned to companies/participants)
CREATE TABLE IF NOT EXISTS project_tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    title TEXT NOT NULL,
    description TEXT,
    skill TEXT NOT NULL,
    phase TEXT,
    priority TEXT DEFAULT 'medium',
    assigned_company TEXT NOT NULL,
    assigned_participants JSONB DEFAULT '[]',
    status TEXT DEFAULT 'pending',
    result TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_companies_code ON companies(code);
CREATE INDEX IF NOT EXISTS idx_influencers_company ON influencers(company_id);
CREATE INDEX IF NOT EXISTS idx_influencers_platform ON influencers(platform);
CREATE INDEX IF NOT EXISTS idx_content_pipeline_status ON content_pipeline(status);
CREATE INDEX IF NOT EXISTS idx_content_pipeline_influencer ON content_pipeline(influencer_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_company ON portfolio(company_id);
CREATE INDEX IF NOT EXISTS idx_portfolio_status ON portfolio(status);
CREATE INDEX IF NOT EXISTS idx_capital_transfers_status ON capital_transfers(status);
CREATE INDEX IF NOT EXISTS idx_ledger_company ON budget_ledger(company_id);
CREATE INDEX IF NOT EXISTS idx_decisions_company ON decisions(company_id);
CREATE INDEX IF NOT EXISTS idx_tasks_company ON agent_tasks(company_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_project_tasks_project ON project_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_project_tasks_company ON project_tasks(assigned_company);
CREATE INDEX IF NOT EXISTS idx_project_tasks_status ON project_tasks(status);

-- Audit log (governance Phase 1) — APPEND-ONLY. Never UPDATE/DELETE.
CREATE TABLE IF NOT EXISTS activity_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID REFERENCES companies(id),
    actor_type TEXT NOT NULL,          -- 'model' | 'agent' | 'user' | 'system'
    actor TEXT NOT NULL,               -- model id / participant name / 'system'
    action TEXT NOT NULL,              -- 'model_call' | 'decision_detected' | 'decision_approved' | 'decision_rejected'
    entity_type TEXT,                  -- 'model_call' | 'decision' | 'project'
    entity_id TEXT,
    details JSONB DEFAULT '{}',
    occurred_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_activity_company ON activity_log(company_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log(company_id, action);
"""

# Seed companies (idempotent — uses ON CONFLICT)
SEED_COMPANIES_SQL = """
INSERT INTO companies (name, code, description, port) VALUES
    ('Holding Company', 'holding', 'Board room — CEO, CFO, COO make strategic decisions and allocate capital', 8130),
    ('MeshTech', 'meshtech', 'Tech company — builds SaaS, APIs, digital tools', 8131),
    ('MeshMedia', 'meshmedia', 'Media company — AI-generated social media influencers', 8132),
    ('MeshCapital', 'meshcapital', 'Investment company — manages portfolio, deploys profits', 8133),
    ('MeshVentures', 'meshventures', 'Ventures — rapid MVP, marketplace products, 3D printing', 8134)
ON CONFLICT (code) DO NOTHING;
"""


async def get_pool() -> asyncpg.Pool:
    """Get or create the connection pool. Auto-initializes schema."""
    global _pool
    if _pool is None:
        for attempt in range(5):
            try:
                _pool = await asyncpg.create_pool(
                    host=DB_HOST, port=DB_PORT, database=DB_NAME,
                    user=DB_USER, password=DB_PASS,
                    min_size=2, max_size=10,
                )
                # Auto-create tables
                async with _pool.acquire() as conn:
                    await conn.execute(SCHEMA_SQL)
                    await conn.execute(SEED_COMPANIES_SQL)
                logger.info("Database initialized successfully")
                break
            except (asyncpg.PostgresError, OSError) as e:
                logger.warning(f"DB connect attempt {attempt+1}/5 failed: {e}")
                if attempt < 4:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error("Could not connect to database after 5 attempts")
                    raise
    return _pool


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ============================================================
# Company queries
# ============================================================

async def get_company_by_code(code: str) -> Optional[dict]:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM companies WHERE code = $1", code)
    return dict(row) if row else None


async def get_all_companies() -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch("SELECT * FROM companies ORDER BY port")
    return [dict(r) for r in rows]


async def get_company_pnl(company_id: UUID) -> dict:
    """Get P&L summary for a company."""
    pool = await get_pool()
    row = await pool.fetchrow("""
        SELECT
            COALESCE(SUM(CASE WHEN transaction_type = 'revenue' THEN amount ELSE 0 END), 0) as revenue,
            COALESCE(SUM(CASE WHEN transaction_type = 'expense' THEN amount ELSE 0 END), 0) as expenses,
            COALESCE(SUM(CASE WHEN transaction_type = 'revenue' THEN amount ELSE -amount END), 0) as net
        FROM budget_ledger WHERE company_id = $1
    """, company_id)
    return dict(row) if row else {"revenue": 0, "expenses": 0, "net": 0}


async def get_holding_rollup() -> list[dict]:
    """Get P&L rollup for all companies (holding company view)."""
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT c.name, c.code, c.budget_allocated, c.total_revenue,
            COALESCE(SUM(CASE WHEN bl.transaction_type = 'revenue' THEN bl.amount ELSE 0 END), 0) as revenue,
            COALESCE(SUM(CASE WHEN bl.transaction_type = 'expense' THEN bl.amount ELSE 0 END), 0) as expenses
        FROM companies c
        LEFT JOIN budget_ledger bl ON bl.company_id = c.id
        WHERE c.code != 'holding'
        GROUP BY c.id ORDER BY c.port
    """)
    return [dict(r) for r in rows]


# ============================================================
# Budget ledger
# ============================================================

async def record_transaction(company_id: UUID, txn_type: str, amount: float,
                             description: str, agent: str = "system") -> UUID:
    pool = await get_pool()
    row = await pool.fetchrow("""
        INSERT INTO budget_ledger (company_id, transaction_type, amount, description, agent)
        VALUES ($1, $2, $3, $4, $5) RETURNING id
    """, company_id, txn_type, amount, description, agent)
    return row["id"]


# ============================================================
# Capital transfers
# ============================================================

async def request_transfer(from_id: UUID, to_id: UUID, amount: float, reason: str) -> UUID:
    pool = await get_pool()
    row = await pool.fetchrow("""
        INSERT INTO capital_transfers (from_company, to_company, amount, reason)
        VALUES ($1, $2, $3, $4) RETURNING id
    """, from_id, to_id, amount, reason)
    return row["id"]


async def approve_transfer(transfer_id: UUID, approved_by: str = "CEO") -> bool:
    pool = await get_pool()
    row = await pool.fetchrow("""
        UPDATE capital_transfers SET status = 'approved', approved_by = $2
        WHERE id = $1 AND status = 'pending' RETURNING id
    """, transfer_id, approved_by)
    return row is not None


async def get_pending_transfers(company_id: Optional[UUID] = None) -> list[dict]:
    pool = await get_pool()
    if company_id:
        rows = await pool.fetch("""
            SELECT ct.*, fc.name as from_name, tc.name as to_name
            FROM capital_transfers ct
            JOIN companies fc ON ct.from_company = fc.id
            JOIN companies tc ON ct.to_company = tc.id
            WHERE ct.status = 'pending' AND (ct.from_company = $1 OR ct.to_company = $1)
            ORDER BY ct.created_at DESC
        """, company_id)
    else:
        rows = await pool.fetch("""
            SELECT ct.*, fc.name as from_name, tc.name as to_name
            FROM capital_transfers ct
            JOIN companies fc ON ct.from_company = fc.id
            JOIN companies tc ON ct.to_company = tc.id
            WHERE ct.status = 'pending'
            ORDER BY ct.created_at DESC
        """)
    return [dict(r) for r in rows]


# ============================================================
# Decisions log
# ============================================================

async def log_decision(company_id: UUID, agent: str, decision_type: str,
                       description: str, reasoning: str = "", cost: float = 0) -> UUID:
    pool = await get_pool()
    row = await pool.fetchrow("""
        INSERT INTO decisions (company_id, agent, decision_type, description, reasoning, cost)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
    """, company_id, agent, decision_type, description, reasoning, cost)
    return row["id"]


async def get_recent_decisions(company_id: UUID, limit: int = 20) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT * FROM decisions WHERE company_id = $1
        ORDER BY created_at DESC LIMIT $2
    """, company_id, limit)
    return [dict(r) for r in rows]


async def get_activity(company_id: UUID, limit: int = 100,
                       action: Optional[str] = None) -> list[dict]:
    pool = await get_pool()
    if action:
        rows = await pool.fetch("""
            SELECT * FROM activity_log
            WHERE company_id = $1 AND action = $2
            ORDER BY occurred_at DESC LIMIT $3
        """, company_id, action, limit)
    else:
        rows = await pool.fetch("""
            SELECT * FROM activity_log
            WHERE company_id = $1
            ORDER BY occurred_at DESC LIMIT $2
        """, company_id, limit)
    return [dict(r) for r in rows]


# ============================================================
# Projects (Fortune 500 workflow)
# ============================================================

async def save_project(project: dict):
    """Save a new project and its tasks."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO projects (id, name, pitch, outline, status)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name, outline = EXCLUDED.outline,
                status = EXCLUDED.status, updated_at = NOW()
        """,
            project["id"],
            project["outline"].get("project_name", "Unknown"),
            project["pitch"],
            json.dumps(project["outline"]),
            project["status"],
        )
        for task in project.get("tasks", []):
            await conn.execute("""
                INSERT INTO project_tasks (id, project_id, title, description, skill,
                    phase, priority, assigned_company, assigned_participants, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (id) DO NOTHING
            """,
                task["id"], project["id"], task["title"], task["description"],
                task["skill"], task.get("phase", ""), task.get("priority", "medium"),
                task["assigned_company"], json.dumps(task["assigned_participants"]),
                task["status"],
            )


async def update_project_status(project_id: str, status: str,
                                 tasks: Optional[list] = None,
                                 synthesis: Optional[str] = None):
    """Update project status and optionally task results."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if synthesis:
            await conn.execute("""
                UPDATE projects SET status = $2, synthesis = $3, updated_at = NOW()
                WHERE id = $1
            """, project_id, status, synthesis)
        else:
            await conn.execute("""
                UPDATE projects SET status = $2, updated_at = NOW() WHERE id = $1
            """, project_id, status)

        if tasks:
            for task in tasks:
                await conn.execute("""
                    UPDATE project_tasks SET status = $2, result = $3,
                        completed_at = CASE WHEN $2 = 'completed' THEN NOW() ELSE NULL END
                    WHERE id = $1
                """, task["id"], task["status"], task.get("result"))


async def get_project(project_id: str) -> Optional[dict]:
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not row:
        return None
    project = dict(row)
    if isinstance(project.get("outline"), str):
        project["outline"] = json.loads(project["outline"])
    tasks = await pool.fetch(
        "SELECT * FROM project_tasks WHERE project_id = $1 ORDER BY created_at", project_id
    )
    project["tasks"] = []
    for t in tasks:
        td = dict(t)
        if isinstance(td.get("assigned_participants"), str):
            td["assigned_participants"] = json.loads(td["assigned_participants"])
        project["tasks"].append(td)
    return project


async def list_projects(limit: int = 50) -> list[dict]:
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT p.id, p.name, p.status, p.created_at,
            COUNT(pt.id) as task_count,
            COUNT(pt.id) FILTER (WHERE pt.status = 'completed') as completed_count
        FROM projects p
        LEFT JOIN project_tasks pt ON pt.project_id = p.id
        GROUP BY p.id ORDER BY p.created_at DESC LIMIT $1
    """, limit)
    return [dict(r) for r in rows]
