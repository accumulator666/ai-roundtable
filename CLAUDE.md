# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Mesh is a multi-AI Docker infrastructure where Claude, ChatGPT, Grok, Gemini, DeepSeek, Ollama, and Claude Code run in separate containers on a shared network. A central router handles request routing, AI-to-AI delegation, and multi-model fan-out. Redis provides async messaging, PostgreSQL stores conversations and routing state. Langflow and n8n sit on top as orchestration/automation layers.

## Architecture

- **AI Proxies** (`proxies/`) — Thin FastAPI wrappers normalizing each API to OpenAI-compatible `/v1/chat/completions` format
  - `claude/` — Translates Anthropic Messages API to/from OpenAI format
  - `chatgpt/` — Passthrough to OpenAI API (already OpenAI format)
  - `grok/` — Passthrough to xAI API (OpenAI-compatible)
  - `gemini/` — Translates Google Gemini API to/from OpenAI format
  - `deepseek/` — Passthrough to DeepSeek API (OpenAI-compatible)
- **Claude Code API** (`claude-code/`) — Wraps Claude Code CLI as REST service, has its own Dockerfile
- **AI Router** (`router/`) — Central orchestrator with auto-routing, delegation, and fan-out
  - `routing.py` — Model-to-proxy mapping, auto-selection logic, health checks
  - `delegation.py` — AI-to-AI delegation via `[DELEGATE:model]` tags, Redis pub/sub
  - `main.py` — FastAPI app with all endpoints
  - `init_db.sql` — PostgreSQL schema for conversations, messages, delegations, usage tracking
- **Shared** (`shared/`) — Pydantic models and config used across services

## Commands

```bash
# Start everything
cd /data/ai-mesh && docker compose up -d

# Check health of all backends
curl http://localhost:8110/health

# View logs for a specific service
docker logs ai-mesh-router -f
docker logs ai-mesh-claude-proxy -f

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

## Auto-Routing Keywords

When `model: "auto"`, the router picks based on message content:
- coding/debug/implement → Claude Opus
- creative/story/essay → GPT-4o
- research/analyze/data → Grok-3
- image/visual/diagram → Gemini Flash
- default → Claude Sonnet

## API Keys

Stored in `.env`. Never commit this file. All keys are injected as environment variables into containers.

## n8n Workflows

Pre-built workflows in `n8n/`:
- `ai-mesh-health-check.json` — Polls router health every 5 min, alerts on degradation
- `ai-router-webhook.json` — Webhook gateway: POST to `/webhook/ai-chat` to proxy through router
- `multi-ai-comparison.json` — POST to `/webhook/ai-compare` to fan-out same prompt to multiple AIs

Import via: `docker cp n8n/<file>.json ai-mesh-n8n:/tmp/ && docker exec ai-mesh-n8n n8n import:workflow --input=/tmp/<file>.json`

n8n UI: http://localhost:5678 (requires first-time setup via browser)

## Development

Code changes are picked up by restarting the container (volumes are mounted). No rebuild needed except for claude-code (which has a Dockerfile).

```bash
# Edit proxy code, then:
docker restart ai-mesh-claude-proxy

# Rebuild claude-code after Dockerfile changes:
docker compose build claude-code && docker compose up -d claude-code

# Add a new proxy: create proxies/<name>/{main.py,requirements.txt},
# add to docker-compose.yml, add to router/routing.py, restart router
```

## Existing Postgres

The Postgres container is from ai-stack (`prompt-template-db`). Default DB is `templates`, NOT `admin`. Always specify `-d templates` or `-d ai_mesh` when connecting:
```bash
docker exec -it prompt-template-db psql -U admin -d ai_mesh
```
