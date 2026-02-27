# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Mesh is a multi-AI Docker infrastructure where Claude, ChatGPT, Grok, Gemini, DeepSeek, Ollama, and Claude Code run in separate containers on a shared network. A central router handles request routing, AI-to-AI delegation, and multi-model fan-out. Redis provides async messaging, PostgreSQL stores conversations and routing state. n8n provides workflow automation. A collab-chat service runs a 65+ participant AI roundtable via WebSockets. CrewAI agents handle autonomous business tasks.

## Architecture

Three-tier system: **Proxies** normalize AI APIs → **Router** orchestrates requests → **Supporting services** handle persistence, automation, and UI.

- **AI Proxies** (`proxies/`) — Thin FastAPI wrappers normalizing each API to OpenAI-compatible `/v1/chat/completions` format
  - `claude/` — Translates Anthropic Messages API to/from OpenAI format (merges consecutive same-role messages, strips trailing assistant messages)
  - `chatgpt/` — Passthrough (handles `max_tokens` → `max_completion_tokens` for GPT-5 family)
  - `grok/` — Passthrough to xAI API
  - `gemini/` — Translates Google Gemini API to/from OpenAI format (converts to `contents` structure)
  - `deepseek/` — Passthrough to DeepSeek API
- **AI Router** (`router/`) — Central orchestrator with auto-routing, delegation, and fan-out
  - `routing.py` — **Source of truth** for model routing: `MODEL_TO_PROXY` dict (40+ models), `AUTO_ROUTE_PATTERNS` regex matching, `R730_MODELS` set, health checks
  - `delegation.py` — Parses `[DELEGATE:model_name]prompt[/DELEGATE]` tags from AI responses, Redis pub/sub
  - `main.py` — FastAPI app: completions, delegation, multi-fan-out, model listing, health
  - `init_db.sql` — PostgreSQL schema for conversations, messages, delegations, usage tracking
- **Collab Chat** (`collab-chat/`) — WebSocket-based multi-AI roundtable. SSE streaming. Frontend in `index.html`.
  - `participants.json` — Editable participant list (65+ entries: raw models + business persona agents)
  - `model_config.json` — Per-model `max_tokens`, `temperature`, `timeout` tuning
  - Automatic backups before edits in `backups/` with manifest; changes logged in `edit_log.md`
- **CrewAI Agents** (`agents/`) — Autonomous business agents (Strategist, Researcher, Builder, Marketer, Finance). YAML-configured in `agents/config/`. Background job execution via REST API. Routes LLM calls through the ai-mesh router.
- **Claude Code API** (`claude-code/`) — Wraps Claude Code CLI as REST service, has its own Dockerfile
- **Shared** (`shared/`) — Pydantic models (`models.py`) and config (`config.py`). **Note:** `shared/config.py` has stale routing mappings; the authoritative routing config is `router/routing.py`.

## Commands

```bash
# Start everything
cd /data/ai-mesh && docker compose up -d

# Check health of all backends
curl -s http://localhost:8110/health | jq

# View logs for a specific service
docker logs ai-mesh-router -f --tail 50

# Restart a single service (picks up code changes from mounted volumes)
docker restart ai-mesh-router

# Run a chat completion through the router
curl -X POST http://localhost:8110/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "Hello"}]}'

# Multi-model fan-out
curl -X POST http://localhost:8110/v1/chat/multi \
  -H "Content-Type: application/json" \
  -d '{"models": ["claude-haiku-4-5", "grok-3-mini", "deepseek-chat"], "messages": [{"role": "user", "content": "Hello"}]}'

# Initialize database (only needed once)
docker exec -i prompt-template-db psql -U admin -d ai_mesh < router/init_db.sql

# Run integration tests
cd /data/ai-mesh && pytest tests/ -v

# Run a single test
pytest tests/test_router.py::test_health -v

# Agent endpoints
curl -s -X POST http://localhost:8120/v1/agents/strategy-session | jq
curl -s http://localhost:8120/v1/agents/jobs | jq
```

## Key Ports

| Service | Port | Container Name |
|---------|------|----------------|
| AI Router | 8110 | ai-mesh-router |
| Claude Proxy | 8100 | ai-mesh-claude-proxy |
| ChatGPT Proxy | 8101 | ai-mesh-chatgpt-proxy |
| Grok Proxy | 8102 | ai-mesh-grok-proxy |
| Gemini Proxy | 8103 | ai-mesh-gemini-proxy |
| DeepSeek Proxy | 8105 | ai-mesh-deepseek-proxy |
| Claude Code | 8104 | ai-mesh-claude-code |
| CrewAI Agents | 8120 | ai-mesh-crewai-agents |
| Collab Chat | 8130 | ai-mesh-collab-chat |
| Redis | 6379 | ai-mesh-redis |
| n8n | 5678 | ai-mesh-n8n |

## Networks

- `ai-mesh_ai-mesh` — Internal network for all ai-mesh services
- `ai-stack_default` — External network bridging to existing services (ollama, postgres, open-webui, langflow)
- Ollama, Open WebUI, and Langflow are connected to both networks

## Router Endpoints

- `POST /v1/chat/completions` — OpenAI-compatible, routes by model name or `"auto"`
- `POST /v1/chat/delegate` — Explicit AI-to-AI delegation
- `POST /v1/chat/multi` — Fan-out to multiple AIs in parallel
- `GET /v1/models` — Aggregated model list from all providers
- `GET /health` — Health status of all backends

## Agent Endpoints

- `POST /v1/agents/strategy-session` — Run a strategy session (background job)
- `POST /v1/agents/build-business` — Build a business plan (accepts `{"business_description": "..."}`)
- `GET /v1/agents/jobs` — List all agent jobs
- `GET /v1/agents/jobs/{job_id}` — Get specific job status/result

## Model Routing

**Anthropic models** route through `claude-code` (Max subscription), not `claude-proxy`.

**Auto-routing:** When `model: "auto"`, the router picks based on message content (`routing.py:AUTO_ROUTE_PATTERNS`):
- coding/debug/implement → GPT-5.2
- creative/story/essay → GPT-5.2
- research/analyze/data → Grok-3
- image/visual/diagram → Gemini 2.0 Flash
- default → Claude Sonnet 4.5

**Fallback chain for unknown models:** Check `R730_MODELS` set → route to R730 Ollama (`R730_OLLAMA_URL`); otherwise → local Ollama.

## Caddy Reverse Proxy

The `Caddyfile` routes external requests:
- `/n8n/*` → n8n:5678
- `/chat/ws` and `/chat/*` → collab-chat:8000
- `/router/*` → ai-router:8000
- `/agents/*` → crewai-agents:8000
- Vaultwarden → `https://192.168.50.23:8444` (internal TLS)
- OpenClaw → `https://192.168.50.23:18443` → port 18789

Uses `$ROUNDTABLE_DOMAIN` env var for dynamic domain configuration.

## API Keys

Stored in `.env`. Never commit this file. All keys are injected as environment variables into containers. Required keys: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`.

## n8n Workflows

Pre-built workflows in `n8n/`:
- `ai-mesh-health-check.json` — Polls router health every 5 min, alerts on degradation
- `ai-router-webhook.json` — Webhook gateway: POST to `/webhook/ai-chat` to proxy through router
- `multi-ai-comparison.json` — POST to `/webhook/ai-compare` to fan-out same prompt to multiple AIs

Import via: `docker cp n8n/<file>.json ai-mesh-n8n:/tmp/ && docker exec ai-mesh-n8n n8n import:workflow --input=/tmp/<file>.json`

n8n UI: http://localhost:5678 (requires first-time setup via browser)

## Development

All services use Python 3.12, FastAPI, uvicorn, httpx, and Pydantic v2. Inter-service calls use httpx AsyncClient with 120s timeout. Streaming uses SSE via `sse-starlette`.

Code changes are picked up by restarting the container (volumes are mounted). No rebuild needed except for claude-code (which has a Dockerfile).

```bash
# Edit proxy code, then:
docker restart ai-mesh-claude-proxy

# Rebuild claude-code after Dockerfile changes:
docker compose build claude-code && docker compose up -d claude-code

# Add a new proxy: create proxies/<name>/{main.py,requirements.txt},
# add to docker-compose.yml, add MODEL_TO_PROXY entries in router/routing.py,
# restart router
```

## Testing

Tests use pytest with httpx. Fixtures in `tests/conftest.py` provide `http_client` and `BASE_URLS` (maps all proxies + router).

```bash
cd /data/ai-mesh && pytest tests/ -v
pytest tests/test_router.py::test_health -v
```

Test files: `test_router.py` (health, models, routing, multi-fan-out), `test_proxies.py` (health checks for each proxy).

## Existing Postgres

The Postgres container is from ai-stack (`prompt-template-db`). Default DB is `templates`, NOT `admin`. Always specify `-d templates` or `-d ai_mesh` when connecting:
```bash
docker exec -it prompt-template-db psql -U admin -d ai_mesh
```
