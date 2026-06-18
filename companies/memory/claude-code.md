# Claude Code — Agent Memory

## My Responsibilities
- Backend architecture (shared/base_app.py, shared/db.py, shared/company_comms.py)
- Docker compose entries for all 5 companies
- Database migrations (auto-init, no manual SQL)
- MeshCapital ↔ Options Trader integration
- MeshMedia ↔ Stable Diffusion/ComfyUI integration
- n8n workflow creation

## Decisions Made
- Extracting collab-chat/main.py into company-aware base_app.py
- Using asyncpg for PostgreSQL (async connection pool)
- Tables auto-create on first startup — no manual init_db.sql needed
- Redis pub/sub channels: `company:{code}:inbox`, `company:broadcast`
- Each company reads COMPANY_CODE env var to scope itself

## Work Log
- 2026-02-27: Created directory structure, memory system
- 2026-02-27: Starting shared/db.py, shared/base_app.py, shared/company_comms.py
