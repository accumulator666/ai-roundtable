import os
import json
import asyncio
from crewai.tools import tool

POSTGRES_CONN = f"postgresql://{os.environ.get('POSTGRES_USER', 'admin')}:{os.environ.get('POSTGRES_PASSWORD', '')}@{os.environ.get('POSTGRES_HOST', 'prompt-template-db')}:5432/{os.environ.get('POSTGRES_DB', 'ai_mesh')}"


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@tool("save_memory")
def save_memory(key: str, value: str, agent: str) -> str:
    """Save a value to shared memory that all agents can access. Use for decisions, plans, context."""
    import asyncpg

    async def _save():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            await conn.execute(
                """INSERT INTO shared_memory (key, value, agent, updated_at)
                   VALUES ($1, $2::jsonb, $3, NOW())
                   ON CONFLICT (key) DO UPDATE SET value = $2::jsonb, agent = $3, updated_at = NOW()""",
                key, json.dumps({"data": value}), agent
            )
            return f"Saved to shared memory: {key}"
        finally:
            await conn.close()

    return _run(_save())


@tool("read_memory")
def read_memory(key: str) -> str:
    """Read a value from shared memory."""
    import asyncpg

    async def _read():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            row = await conn.fetchrow("SELECT value, agent, updated_at FROM shared_memory WHERE key = $1", key)
            if row:
                val = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                return f"Key: {key}\nValue: {val.get('data', val)}\nSet by: {row['agent']}\nUpdated: {row['updated_at']}"
            return f"No memory found for key: {key}"
        finally:
            await conn.close()

    return _run(_read())


@tool("list_memories")
def list_memories() -> str:
    """List all keys in shared memory."""
    import asyncpg

    async def _list():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            rows = await conn.fetch("SELECT key, agent, updated_at FROM shared_memory ORDER BY updated_at DESC LIMIT 50")
            if not rows:
                return "Shared memory is empty."
            lines = [f"  {r['key']} (by {r['agent']}, {r['updated_at']})" for r in rows]
            return "Shared memory keys:\n" + "\n".join(lines)
        finally:
            await conn.close()

    return _run(_list())
