import os
import json
import time
import uuid
import asyncio
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pathlib import Path

app = FastAPI(title="AI Roundtable Chat", version="1.0.0")

ROUTER_URL = os.environ.get("ROUTER_URL", "http://ai-mesh-router:8000")

# Models to include in the roundtable
ROUNDTABLE_MODELS = [
    {"id": "claude-sonnet-4-5", "name": "Claude", "color": "#cc785c"},
    {"id": "grok-3-mini", "name": "Grok", "color": "#1da1f2"},
    {"id": "deepseek-chat", "name": "DeepSeek", "color": "#4a90d9"},
]

# Conversation history shared by all
conversation_history: list[dict] = []

# Connected websocket clients
connected_clients: list[WebSocket] = []


async def broadcast(message: dict):
    """Send message to all connected clients."""
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_clients.remove(ws)


async def ask_model(model_id: str, model_name: str, messages: list[dict]):
    """Ask a single AI model and stream the response."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{ROUTER_URL}/v1/chat/completions",
                json={
                    "model": model_id,
                    "messages": messages,
                    "max_tokens": 2048,
                    "temperature": 0.8,
                },
            )
            if resp.status_code != 200:
                return f"[Error: HTTP {resp.status_code}]"
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[Error: {str(e)[:100]}]"


async def run_roundtable(user_message: str):
    """Run a roundtable discussion round."""
    # Add user message to history
    conversation_history.append({"role": "user", "name": "You", "content": user_message})
    await broadcast({"type": "message", "role": "user", "name": "You", "content": user_message})

    # Build system prompt for roundtable context
    system_prompt = (
        "You are in a roundtable discussion with other AI models and a human user. "
        "You can see what other AIs have said. Be yourself — share your unique perspective, "
        "agree or disagree with others, build on their ideas, or offer alternatives. "
        "Keep responses concise (2-4 paragraphs max). Address other AIs by name when responding to them. "
        "Be collaborative and constructive."
    )

    # Ask all models in parallel
    tasks = []
    for model in ROUNDTABLE_MODELS:
        # Build messages for this model
        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history (map names to context)
        for msg in conversation_history:
            if msg["role"] == "user":
                messages.append({"role": "user", "content": msg["content"]})
            else:
                # Other AI responses shown as user messages with name prefix
                if msg.get("name") == model["name"]:
                    messages.append({"role": "assistant", "content": msg["content"]})
                else:
                    messages.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})

        tasks.append((model, messages))

    # Signal that AIs are thinking
    for model in ROUNDTABLE_MODELS:
        await broadcast({"type": "thinking", "name": model["name"], "color": model["color"]})

    # Run all model calls in parallel
    async def call_model(model, messages):
        response = await ask_model(model["id"], model["name"], messages)
        return model, response

    results = await asyncio.gather(*[call_model(m, msgs) for m, msgs in tasks])

    # Broadcast results as they come
    for model, response in results:
        msg = {"role": "assistant", "name": model["name"], "content": response}
        conversation_history.append(msg)
        await broadcast({
            "type": "message",
            "role": "assistant",
            "name": model["name"],
            "color": model["color"],
            "content": response,
        })

    # After all AIs respond, optionally let them react to each other
    # (This creates a follow-up round where each AI can comment on others)


async def run_cross_talk():
    """Let AIs respond to each other's latest messages (optional follow-up round)."""
    system_prompt = (
        "You just heard other AI models respond to a question. "
        "If you have something meaningful to add, agree/disagree with, or build on, "
        "share a brief follow-up (1-2 paragraphs). If you have nothing to add, just say 'I agree' or stay silent. "
        "Don't repeat what you already said."
    )

    for model in ROUNDTABLE_MODELS:
        messages = [{"role": "system", "content": system_prompt}]
        for msg in conversation_history[-10:]:  # Last 10 messages for context
            if msg["role"] == "user":
                messages.append({"role": "user", "content": msg["content"]})
            elif msg.get("name") == model["name"]:
                messages.append({"role": "assistant", "content": msg["content"]})
            else:
                messages.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})

        await broadcast({"type": "thinking", "name": model["name"], "color": model["color"]})
        response = await ask_model(model["id"], model["name"], messages)

        if response.strip().lower() not in ("i agree", "i agree.", ""):
            msg = {"role": "assistant", "name": model["name"], "content": response}
            conversation_history.append(msg)
            await broadcast({
                "type": "message",
                "role": "assistant",
                "name": model["name"],
                "color": model["color"],
                "content": response,
            })


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)

    # Send existing conversation history
    for msg in conversation_history:
        model_info = next((m for m in ROUNDTABLE_MODELS if m["name"] == msg.get("name")), None)
        await websocket.send_json({
            "type": "message",
            "role": msg["role"],
            "name": msg.get("name", "You"),
            "color": model_info["color"] if model_info else "#ffffff",
            "content": msg["content"],
        })

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "message":
                await run_roundtable(data["content"])
            elif data.get("type") == "crosstalk":
                await run_cross_talk()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(content=html_path.read_text())


@app.get("/health")
async def health():
    return {"status": "ok", "service": "collab-chat", "models": [m["name"] for m in ROUNDTABLE_MODELS]}


@app.post("/api/models")
async def update_models(models: list[dict]):
    """Update which models are in the roundtable."""
    global ROUNDTABLE_MODELS
    ROUNDTABLE_MODELS = models
    return {"status": "updated", "models": ROUNDTABLE_MODELS}


@app.post("/api/clear")
async def clear_history():
    """Clear conversation history."""
    conversation_history.clear()
    await broadcast({"type": "clear"})
    return {"status": "cleared"}
