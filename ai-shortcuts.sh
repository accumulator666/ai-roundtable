#!/bin/bash
# AI Mesh shell shortcuts — sourced from ~/.bashrc

_ai_chat() {
    local model="$1"
    shift
    local prompt="$*"
    if [ -z "$prompt" ]; then
        echo "Usage: ai-${model} \"your prompt here\""
        return 1
    fi
    curl -s -X POST http://localhost:8110/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d "$(jq -n --arg m "$model" --arg p "$prompt" '{model: $m, messages: [{role: "user", content: $p}]}')" \
        | jq -r '.choices[0].message.content // .detail'
}

# Chat with auto-routing
function ai { _ai_chat "auto" "$@"; }

# Chat with specific providers
function ai-claude   { _ai_chat "claude-sonnet-4-5" "$@"; }
function ai-grok     { _ai_chat "grok-3-mini" "$@"; }
function ai-gpt      { _ai_chat "gpt-4o-mini" "$@"; }
function ai-gemini   { _ai_chat "gemini-2.0-flash" "$@"; }
function ai-deepseek { _ai_chat "deepseek-chat" "$@"; }

# Ask all AIs the same prompt
function ai-multi {
    local prompt="$*"
    if [ -z "$prompt" ]; then
        echo "Usage: ai-multi \"your prompt here\""
        return 1
    fi
    curl -s -X POST http://localhost:8110/v1/chat/multi \
        -H "Content-Type: application/json" \
        -d "$(jq -n --arg p "$prompt" '{
            models: ["claude-haiku-4-5", "grok-3-mini", "gpt-4o-mini", "gemini-2.0-flash", "deepseek-chat"],
            messages: [{role: "user", content: $p}]
        }')" \
        | jq -r '.results[] | "\n━━━ \(.model) ━━━\n\(.response.choices[0].message.content // .error)"'
}

# Health & management
function ai-health   { curl -s http://localhost:8110/health | jq; }
function ai-models   { curl -s http://localhost:8110/v1/models | jq -r '.data[].id' | sort; }
function ai-logs     { docker logs "ai-mesh-${1:-router}" -f --tail 50; }
function ai-restart  { docker restart "ai-mesh-${1:-router}"; }
function ai-up       { cd /data/ai-mesh && docker compose up -d; }
function ai-down     { cd /data/ai-mesh && docker compose down; }

# Agent commands
function ai-strategy { curl -s -X POST http://localhost:8120/v1/agents/strategy-session | jq; }
function ai-build    { curl -s -X POST http://localhost:8120/v1/agents/build-business -H "Content-Type: application/json" -d "$(jq -n --arg d "$*" '{business_description: $d}')" | jq; }
function ai-jobs     { curl -s http://localhost:8120/v1/agents/jobs | jq; }
function ai-job      { curl -s http://localhost:8120/v1/agents/jobs/$1 | jq; }
