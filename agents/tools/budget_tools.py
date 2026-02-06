import os
import asyncio
from crewai.tools import tool

POSTGRES_CONN = f"postgresql://{os.environ.get('POSTGRES_USER', 'admin')}:{os.environ.get('POSTGRES_PASSWORD', '')}@{os.environ.get('POSTGRES_HOST', 'prompt-template-db')}:5432/{os.environ.get('POSTGRES_DB', 'ai_mesh')}"

LIMIT_PER_ACTION = float(os.environ.get("SPENDING_LIMIT_PER_ACTION", 20))
LIMIT_DAILY = float(os.environ.get("SPENDING_LIMIT_DAILY", 100))
REINVEST_PERCENT = float(os.environ.get("REVENUE_REINVEST_PERCENT", 10))


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


@tool("check_budget")
def check_budget() -> str:
    """Check current budget status including autonomous pool, daily spending, and limits."""
    import asyncpg

    async def _check():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            daily_spent = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'expense' AND created_at >= CURRENT_DATE"
            )
            total_revenue = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'revenue'"
            )
            total_expenses = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'expense'"
            )
            autonomous_pool = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'reinvestment'"
            )
            pool_spent = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'expense' AND approved_by = 'auto'"
            )
            available_pool = float(autonomous_pool) - float(pool_spent)
            return (
                f"Daily spent: ${daily_spent:.2f} / ${LIMIT_DAILY:.2f}\n"
                f"Per-action limit: ${LIMIT_PER_ACTION:.2f}\n"
                f"Total revenue: ${total_revenue:.2f}\n"
                f"Total expenses: ${total_expenses:.2f}\n"
                f"Net profit: ${float(total_revenue) - float(total_expenses):.2f}\n"
                f"Autonomous pool: ${available_pool:.2f}\n"
                f"Reinvest rate: {REINVEST_PERCENT}%"
            )
        finally:
            await conn.close()

    return _run(_check())


@tool("record_expense")
def record_expense(amount: float, description: str, agent: str, business_id: str = None) -> str:
    """Record an expense. Returns 'approved' if under limits, 'blocked' if over."""
    import asyncpg

    if amount > LIMIT_PER_ACTION:
        return f"BLOCKED: ${amount:.2f} exceeds per-action limit of ${LIMIT_PER_ACTION:.2f}. Needs human approval."

    async def _record():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            daily_spent = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'expense' AND created_at >= CURRENT_DATE"
            )
            if float(daily_spent) + amount > LIMIT_DAILY:
                return f"BLOCKED: Daily limit would be exceeded. Spent today: ${daily_spent:.2f}, limit: ${LIMIT_DAILY:.2f}"

            await conn.execute(
                "INSERT INTO budget_ledger (business_id, transaction_type, amount, description, agent, approved_by) VALUES ($1, 'expense', $2, $3, $4, 'auto')",
                business_id, amount, description, agent
            )
            return f"APPROVED: ${amount:.2f} recorded for {description}"
        finally:
            await conn.close()

    return _run(_record())


@tool("record_revenue")
def record_revenue(amount: float, description: str, business_id: str, stripe_transaction_id: str = None) -> str:
    """Record revenue from a payment."""
    import asyncpg

    async def _record():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            await conn.execute(
                "INSERT INTO budget_ledger (business_id, transaction_type, amount, description, agent, stripe_transaction_id) VALUES ($1, 'revenue', $2, $3, 'finance', $4)",
                business_id, amount, description, stripe_transaction_id
            )
            await conn.execute(
                "UPDATE businesses SET total_revenue = total_revenue + $1 WHERE id = $2::uuid",
                amount, business_id
            )
            return f"Revenue recorded: ${amount:.2f} for {description}"
        finally:
            await conn.close()

    return _run(_record())
