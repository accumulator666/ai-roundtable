import os
import json
import time
import uuid
import asyncio
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

app = FastAPI(title="AI Roundtable Chat", version="2.0.0")

ROUTER_URL = os.environ.get("ROUTER_URL", "http://ai-mesh-router:8000")

# All available participants — models and agents
ALL_PARTICIPANTS = [
    # --- Raw AI Models (no persona, just the model) ---
    {"id": "claude-sonnet-4-5", "name": "Claude", "color": "#cc785c", "type": "model", "persona": None, "enabled": True},
    {"id": "grok-3-mini", "name": "Grok", "color": "#1da1f2", "type": "model", "persona": None, "enabled": True},
    {"id": "deepseek-chat", "name": "DeepSeek", "color": "#4a90d9", "type": "model", "persona": None, "enabled": False},
    {"id": "qwen2.5:latest", "name": "Qwen", "color": "#7c3aed", "type": "model", "persona": None, "enabled": True},
    {"id": "dolphin-llama3:8b", "name": "Dolphin", "color": "#06b6d4", "type": "model", "persona": None, "enabled": True},
    {"id": "nous-hermes2:latest", "name": "Hermes", "color": "#f59e0b", "type": "model", "persona": None, "enabled": True},
    {"id": "dolphin-mistral:latest", "name": "Mistral", "color": "#ff6b6b", "type": "model", "persona": None, "enabled": False},
    {"id": "wizardlm-uncensored:13b", "name": "Wizard", "color": "#a855f7", "type": "model", "persona": None, "enabled": False},

    # --- Agents (model + persona/expertise) ---
    {"id": "claude-sonnet-4-5", "name": "Strategist", "color": "#10b981", "type": "agent", "enabled": False,
     "persona": "You are the Chief Strategist — a visionary CEO who spots market opportunities, thinks in ROI and scalability, and creates actionable business plans. You prefer automated digital businesses. Always consider budget constraints and time-to-revenue."},

    {"id": "grok-3-mini", "name": "Researcher", "color": "#ec4899", "type": "agent", "enabled": False,
     "persona": "You are the Market Researcher — a data-driven analyst who validates ideas with real numbers. You research competitors, market sizes, pricing, trends, and risks. You're honest about bad ideas and always cite specific data points."},

    {"id": "claude-sonnet-4-5", "name": "Builder", "color": "#3b82f6", "type": "agent", "enabled": False,
     "persona": "You are the Technical Builder — a full-stack developer who ships fast. You know Next.js, Tailwind, Stripe, Cloudflare, Vercel. You suggest practical architectures, estimate build times, and focus on MVPs. You always think about deployment and scaling."},

    {"id": "qwen2.5:latest", "name": "Marketer", "color": "#f97316", "type": "agent", "enabled": False,
     "persona": "You are the Growth Marketer — a conversion-focused copywriter and growth hacker. You write headlines that grab attention, understand SEO, content marketing, email sequences, and social media strategy. Always include specific tactics and CTAs."},

    {"id": "claude-sonnet-4-5", "name": "Finance", "color": "#14b8a6", "type": "agent", "enabled": False,
     "persona": "You are the Finance Manager — a cautious CFO who watches every dollar. You analyze costs, pricing strategy, break-even points, unit economics, and P&L. You enforce spending limits and always ask 'what's the ROI?' before approving anything."},

    {"id": "dolphin-llama3:8b", "name": "Devil's Advocate", "color": "#ef4444", "type": "agent", "enabled": False,
     "persona": "You are the Devil's Advocate — your job is to challenge every idea, find flaws, and stress-test assumptions. You're not negative, you're rigorous. You ask the hard questions others avoid. If an idea survives your scrutiny, it's worth pursuing."},

    {"id": "nous-hermes2:latest", "name": "Creative", "color": "#d946ef", "type": "agent", "enabled": False,
     "persona": "You are the Creative Director — you think outside the box, suggest unconventional approaches, and find unique angles. You combine ideas from different industries and spot opportunities others miss. You're imaginative but practical."},
]

# Conversation history shared by all
conversation_history: list[dict] = []

# Connected websocket clients
connected_clients: list[WebSocket] = []


def get_active_participants():
    return [p for p in ALL_PARTICIPANTS if p.get("enabled", False)]


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
    active = get_active_participants()
    if not active:
        await broadcast({"type": "message", "role": "assistant", "name": "System", "color": "#666", "content": "No participants enabled. Toggle some on in the sidebar."})
        return

    # Add user message to history
    conversation_history.append({"role": "user", "name": "You", "content": user_message})
    await broadcast({"type": "message", "role": "user", "name": "You", "content": user_message})

    # Build base roundtable context
    base_prompt = (
        "You are in a roundtable discussion with other AI models/agents and a human user. "
        "You can see what others have said. Share your unique perspective, "
        "agree or disagree with others, build on their ideas, or offer alternatives. "
        "Keep responses concise (2-4 paragraphs max). Address others by name when responding to them. "
        "Be collaborative and constructive."
    )

    # Build tasks for each participant
    tasks = []
    for participant in active:
        # Build system prompt — combine roundtable context with persona if agent
        if participant.get("persona"):
            system_prompt = f"{participant['persona']}\n\n{base_prompt}"
        else:
            system_prompt = base_prompt

        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history
        for msg in conversation_history:
            if msg["role"] == "user":
                messages.append({"role": "user", "content": msg["content"]})
            else:
                if msg.get("name") == participant["name"]:
                    messages.append({"role": "assistant", "content": msg["content"]})
                else:
                    messages.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})

        tasks.append((participant, messages))

    # Signal thinking
    for p in active:
        await broadcast({"type": "thinking", "name": p["name"], "color": p["color"]})

    # Run all in parallel
    async def call_participant(participant, messages):
        response = await ask_model(participant["id"], participant["name"], messages)
        # Broadcast as soon as this one finishes
        msg = {"role": "assistant", "name": participant["name"], "content": response}
        conversation_history.append(msg)
        await broadcast({
            "type": "message",
            "role": "assistant",
            "name": participant["name"],
            "color": participant["color"],
            "badge": participant["type"],
            "content": response,
        })
        return participant, response

    await asyncio.gather(*[call_participant(p, msgs) for p, msgs in tasks])


async def run_cross_talk():
    """Let participants respond to each other's latest messages."""
    active = get_active_participants()

    base_prompt = (
        "You just heard others respond. "
        "If you have something meaningful to add, agree/disagree with, or build on, "
        "share a brief follow-up (1-2 paragraphs). If nothing to add, say 'Nothing to add.' "
        "Don't repeat yourself."
    )

    for participant in active:
        if participant.get("persona"):
            system_prompt = f"{participant['persona']}\n\n{base_prompt}"
        else:
            system_prompt = base_prompt

        messages = [{"role": "system", "content": system_prompt}]
        for msg in conversation_history[-12:]:
            if msg["role"] == "user":
                messages.append({"role": "user", "content": msg["content"]})
            elif msg.get("name") == participant["name"]:
                messages.append({"role": "assistant", "content": msg["content"]})
            else:
                messages.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})

        await broadcast({"type": "thinking", "name": participant["name"], "color": participant["color"]})
        response = await ask_model(participant["id"], participant["name"], messages)

        skip = response.strip().lower().rstrip(".") in ("nothing to add", "i agree", "")
        if not skip:
            msg = {"role": "assistant", "name": participant["name"], "content": response}
            conversation_history.append(msg)
            await broadcast({
                "type": "message",
                "role": "assistant",
                "name": participant["name"],
                "color": participant["color"],
                "badge": participant["type"],
                "content": response,
            })


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)

    # Send participant list
    await websocket.send_json({"type": "participants", "data": ALL_PARTICIPANTS})

    # Send existing conversation history
    for msg in conversation_history:
        p = next((p for p in ALL_PARTICIPANTS if p["name"] == msg.get("name")), None)
        await websocket.send_json({
            "type": "message",
            "role": msg["role"],
            "name": msg.get("name", "You"),
            "color": p["color"] if p else "#ffffff",
            "badge": p["type"] if p else None,
            "content": msg["content"],
        })

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "message":
                await run_roundtable(data["content"])
            elif data.get("type") == "crosstalk":
                await run_cross_talk()
            elif data.get("type") == "toggle":
                # Toggle a participant on/off
                name = data.get("name")
                for p in ALL_PARTICIPANTS:
                    if p["name"] == name:
                        p["enabled"] = not p["enabled"]
                        break
                await broadcast({"type": "participants", "data": ALL_PARTICIPANTS})
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "index.html"
    return HTMLResponse(content=html_path.read_text())


@app.get("/health")
async def health():
    active = get_active_participants()
    return {"status": "ok", "service": "collab-chat", "active": [p["name"] for p in active], "total": len(ALL_PARTICIPANTS)}


@app.post("/api/clear")
async def clear_history():
    """Clear conversation history."""
    conversation_history.clear()
    await broadcast({"type": "clear"})
    return {"status": "cleared"}
