import asyncpg
import json
from meshcorp.config import POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

pool: asyncpg.Pool | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mc_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT DEFAULT 'briefcase',
    description TEXT,
    roles JSONB NOT NULL DEFAULT '[]',
    default_milestones JSONB DEFAULT '[]',
    skill_tags JSONB DEFAULT '[]',
    is_custom BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mc_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    template_id TEXT REFERENCES mc_templates(id),
    status TEXT DEFAULT 'planning',
    team JSONB NOT NULL DEFAULT '[]',
    budget_allocated NUMERIC(12,2) DEFAULT 0,
    budget_spent NUMERIC(12,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mc_milestones (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES mc_projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    deliverable TEXT,
    status TEXT DEFAULT 'pending',
    result TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mc_messages (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES mc_projects(id) ON DELETE CASCADE,
    milestone_id TEXT,
    role TEXT NOT NULL,
    participant_name TEXT,
    participant_model TEXT,
    content TEXT NOT NULL,
    skill_tags JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mc_actions (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES mc_projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    urgency TEXT DEFAULT 'normal',
    status TEXT DEFAULT 'pending',
    blocking_milestone TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mc_budget_ledger (
    id SERIAL PRIMARY KEY,
    project_id TEXT REFERENCES mc_projects(id) ON DELETE CASCADE,
    amount NUMERIC(12,2) NOT NULL,
    description TEXT,
    category TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mc_notifications (
    id SERIAL PRIMARY KEY,
    action_id TEXT,
    channel TEXT NOT NULL,
    status TEXT DEFAULT 'sent',
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


async def init_db():
    global pool
    pool = await asyncpg.create_pool(
        host=POSTGRES_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        min_size=2,
        max_size=10,
    )
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    await seed_templates()


async def seed_templates():
    """Upsert org templates from JSON files into mc_templates table."""
    import os
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    async with pool.acquire() as conn:
        for filename in os.listdir(template_dir):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(template_dir, filename)) as f:
                data = json.load(f)
            await conn.execute(
                """
                INSERT INTO mc_templates (id, name, icon, description, roles, default_milestones, skill_tags)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    icon = EXCLUDED.icon,
                    description = EXCLUDED.description,
                    roles = EXCLUDED.roles,
                    default_milestones = EXCLUDED.default_milestones,
                    skill_tags = EXCLUDED.skill_tags
                """,
                data["id"],
                data["name"],
                data.get("icon", "briefcase"),
                data.get("description", ""),
                json.dumps(data.get("roles", [])),
                json.dumps(data.get("default_milestones", [])),
                json.dumps(data.get("skill_tags", [])),
            )


async def get_pool() -> asyncpg.Pool:
    if pool is None:
        await init_db()
    return pool
