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
ai() { _ai_chat "auto" "$@"; }

# Chat with specific providers
ai-claude()   { _ai_chat "claude-sonnet-4-5" "$@"; }
ai-grok()     { _ai_chat "grok-3-mini" "$@"; }
ai-gpt()      { _ai_chat "gpt-4o-mini" "$@"; }
ai-gemini()   { _ai_chat "gemini-2.0-flash" "$@"; }
ai-deepseek() { _ai_chat "deepseek-chat" "$@"; }

# Ask all AIs the same prompt
ai-multi() {
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
ai-health()  { curl -s http://localhost:8110/health | jq; }
ai-models()  { curl -s http://localhost:8110/v1/models | jq -r '.data[].id' | sort; }
ai-logs()    { docker logs "ai-mesh-${1:-router}" -f --tail 50; }
ai-restart() { docker restart "ai-mesh-${1:-router}"; }
ai-up()      { cd /data/ai-mesh && docker compose up -d; }
ai-down()    { cd /data/ai-mesh && docker compose down; }

# Agent commands
ai-strategy()  { curl -s -X POST http://localhost:8120/v1/agents/strategy-session | jq; }
ai-build()     { curl -s -X POST http://localhost:8120/v1/agents/build-business -H "Content-Type: application/json" -d "$(jq -n --arg d "$*" '{business_description: $d}')" | jq; }
ai-jobs()      { curl -s http://localhost:8120/v1/agents/jobs | jq; }
ai-job()       { curl -s http://localhost:8120/v1/agents/jobs/$1 | jq; }
