"""MeshMedia — Media Company — port 8132
AI-generated influencers, content pipeline, social media automation.
"""
import sys
sys.path.insert(0, "/app")
from shared.base_app import create_company_app


def add_media_routes(app):
    """Influencer and content pipeline endpoints."""

    @app.get("/api/influencers")
    async def list_influencers():
        try:
            from shared.db import get_pool
            pool = await get_pool()
            rows = await pool.fetch("""
                SELECT * FROM influencers
                WHERE company_id = (SELECT id FROM companies WHERE code = 'meshmedia')
                ORDER BY created_at DESC
            """)
            return {"influencers": [dict(r) for r in rows]}
        except Exception as e:
            return {"error": str(e)}

    @app.get("/api/content-pipeline")
    async def list_content():
        try:
            from shared.db import get_pool
            pool = await get_pool()
            rows = await pool.fetch("""
                SELECT cp.*, i.name as influencer_name
                FROM content_pipeline cp
                JOIN influencers i ON cp.influencer_id = i.id
                ORDER BY cp.created_at DESC LIMIT 50
            """)
            return {"content": [dict(r) for r in rows]}
        except Exception as e:
            return {"error": str(e)}

    @app.post("/api/influencers")
    async def create_influencer(request: dict):
        try:
            import json
            from shared.db import get_pool
            pool = await get_pool()
            row = await pool.fetchrow("""
                INSERT INTO influencers (company_id, name, platform, persona)
                VALUES (
                    (SELECT id FROM companies WHERE code = 'meshmedia'),
                    $1, $2, $3::jsonb
                ) RETURNING id, name, platform
            """, request["name"], request["platform"], json.dumps(request.get("persona", {})))
            return {"influencer": dict(row)}
        except Exception as e:
            return {"error": str(e)}


app = create_company_app(extra_routes=add_media_routes)
