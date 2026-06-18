# Shared Status — Multi-Agent Coordination

**All agents MUST read this file before starting work and update it when they complete tasks.**
**This prevents duplicate work. If someone already did it, don't redo it.**

Last updated: 2026-02-27 19:54 UTC

## Architecture Decisions (locked — don't change without board approval)
- Holding company model: 1 board + 4 subsidiaries
- Each company = separate Docker container, shared codebase in `companies/shared/`
- Database: PostgreSQL `ai_mesh`, company-scoped with `company_id` columns
- Cross-company comms: Redis pub/sub
- Ports: holding=8130, meshtech=8131, meshmedia=8132, meshcapital=8133, meshventures=8134

## Completed Work
- [x] Directory structure created: `companies/{shared,holding,meshtech,meshmedia,meshcapital,meshventures,research,memory}/`
- [x] Memory system created (this file + per-agent files)

## In Progress
- [ ] Claude Code: Building `shared/base_app.py` (company-aware roundtable backend)
- [ ] Claude Code: Building `shared/db.py` (auto-init PostgreSQL, no manual SQL needed)
- [ ] Claude Code: Building `shared/company_comms.py` (Redis cross-company messaging)

## Not Started — Assigned
- [ ] Codex: Frontend dashboard (`companies/shared/base_index.html`)
- [ ] Grok: Research reports in `companies/research/`
- [ ] OpenCode: Split participants into per-company JSON files
- [ ] OpenCode: Create `company_config.json` per company
- [ ] OpenCode: New agent personas + integration tests

## Blockers
(none yet)

## Key Files
| File | Owner | Purpose |
|------|-------|---------|
| `companies/shared/base_app.py` | Claude Code | Shared backend all companies import |
| `companies/shared/db.py` | Claude Code | Database layer (auto-init) |
| `companies/shared/company_comms.py` | Claude Code | Redis cross-company messaging |
| `companies/shared/base_index.html` | Codex | Shared frontend template |
| `companies/*/participants.json` | OpenCode | Per-company team rosters |
| `companies/*/company_config.json` | OpenCode | Per-company budgets/KPIs |
| `companies/research/*.md` | Grok | Research reports |
