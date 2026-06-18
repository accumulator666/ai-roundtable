"""MeshCapital — Investment Company — port 8133
Manages portfolio, deploys profits, connects to options trader.
"""
import os
import sys
sys.path.insert(0, "/app")

import httpx
from shared.base_app import create_company_app

OPTIONS_TRADER_URL = os.environ.get("OPTIONS_TRADER_URL", "http://192.168.50.23:8140")


def add_capital_routes(app):
    """Portfolio and investment endpoints."""

    @app.get("/api/portfolio")
    async def get_portfolio():
        try:
            from shared.db import get_pool
            pool = await get_pool()
            rows = await pool.fetch("""
                SELECT * FROM portfolio
                WHERE company_id = (SELECT id FROM companies WHERE code = 'meshcapital')
                ORDER BY created_at DESC
            """)
            return {"positions": [dict(r) for r in rows]}
        except Exception as e:
            return {"error": str(e)}

    @app.get("/api/options-status")
    async def options_status():
        """Get status from the autonomous options trader."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{OPTIONS_TRADER_URL}/status")
                return resp.json()
        except Exception as e:
            return {"error": f"Options trader unreachable: {e}"}

    @app.get("/api/transfers/pending")
    async def pending_transfers():
        try:
            from shared.db import get_pending_transfers, get_company_by_code
            company = await get_company_by_code("meshcapital")
            if company:
                return {"transfers": await get_pending_transfers(company["id"])}
            return {"transfers": []}
        except Exception as e:
            return {"error": str(e)}


app = create_company_app(extra_routes=add_capital_routes)
