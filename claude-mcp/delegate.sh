#!/bin/bash
# Quick delegation helper — call from Claude Code via Bash
# Usage: delegate.sh <task_type> "prompt"
# Task types: research, code, review, analyze, summarize, creative, debug, ask
# Examples:
#   delegate.sh research "What sells best on Etsy for 3D printing?"
#   delegate.sh code "Write a Python FastAPI endpoint that accepts file uploads"
#   delegate.sh review "$(cat myfile.py)"
#   delegate.sh ask "grok-3-mini" "What is the current price of Bitcoin?"

ROUTER="http://localhost:8110"
TASK="${1:-research}"
shift

# Model routing by task type
case "$TASK" in
  research)   MODEL="grok-3-mini";           SYSTEM="You are a thorough researcher. Be concise but comprehensive." ;;
  code)       MODEL="qwen3:30b";      SYSTEM="You are an expert coder. Output ONLY code, no explanations unless asked." ;;
  code_heavy) MODEL="deepseek-coder:33b";    SYSTEM="You are a senior developer. Write production-ready code." ;;
  review)     MODEL="deepseek-coder:33b";    SYSTEM="You are a code reviewer. Flag bugs, security issues, and performance problems." ;;
  analyze)    MODEL="qwen3:30b";        SYSTEM="You are a data analyst. Be precise and evidence-based." ;;
  summarize)  MODEL="dolphin-llama3:8b";     SYSTEM="Summarize concisely. Keep key details." ;;
  creative)   MODEL="dolphin-mistral:latest"; SYSTEM="You are a creative copywriter. Be bold and compelling." ;;
  debug)      MODEL="deepseek-coder:33b";    SYSTEM="You are a debugging expert. Identify root causes and suggest fixes." ;;
  ask)        MODEL="$1"; shift;              SYSTEM="" ;;
  *)          MODEL="nous-hermes2:latest";    SYSTEM="Be helpful and concise." ;;
esac

PROMPT="$*"

if [ -z "$PROMPT" ]; then
  echo "Usage: delegate.sh <task_type> \"prompt\""
  echo "Types: research, code, code_heavy, review, analyze, summarize, creative, debug, ask"
  exit 1
fi

# Build JSON payload
PAYLOAD=$(python3 -c "
import json, sys
messages = []
system = '''$SYSTEM'''
if system:
    messages.append({'role': 'system', 'content': system})
messages.append({'role': 'user', 'content': sys.stdin.read()})
print(json.dumps({'model': '$MODEL', 'messages': messages, 'max_tokens': 4096, 'temperature': 0.7}))
" <<< "$PROMPT")

# Call the router
RESPONSE=$(curl -s --max-time 120 "$ROUTER/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

# Extract content
echo "$RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    content = d['choices'][0]['message']['content']
    model = d.get('model', '$MODEL')
    usage = d.get('usage', {})
    tokens = usage.get('total_tokens', '?')
    print(f'[{model} | {tokens} tokens]')
    print(content)
except Exception as e:
    print(f'[Error: {e}]')
    print(d if 'd' in dir() else 'No response')
" 2>&1
