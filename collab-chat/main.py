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
# Strategy: cloud models ($$$) for high-stakes decisions, local models (FREE) for research/analysis
# Local = qwen2.5, dolphin-llama3:8b, nous-hermes2, dolphin-mistral, wizardlm-uncensored:13b
# Cloud = claude-sonnet-4-5, grok-3-mini, deepseek-chat
ALL_PARTICIPANTS = [
    # --- Raw AI Models (no persona, just the model) ---
    {"id": "claude-sonnet-4-5", "name": "Claude", "color": "#cc785c", "type": "model", "persona": None, "enabled": False},
    {"id": "grok-3-mini", "name": "Grok", "color": "#1da1f2", "type": "model", "persona": None, "enabled": False},
    {"id": "deepseek-chat", "name": "DeepSeek", "color": "#4a90d9", "type": "model", "persona": None, "enabled": False},
    {"id": "qwen2.5:latest", "name": "Qwen", "color": "#7c3aed", "type": "model", "persona": None, "enabled": False},
    {"id": "dolphin-llama3:8b", "name": "Dolphin", "color": "#06b6d4", "type": "model", "persona": None, "enabled": False},
    {"id": "nous-hermes2:latest", "name": "Hermes", "color": "#f59e0b", "type": "model", "persona": None, "enabled": False},
    {"id": "dolphin-mistral:latest", "name": "Mistral", "color": "#ff6b6b", "type": "model", "persona": None, "enabled": False},
    {"id": "wizardlm-uncensored:13b", "name": "Wizard", "color": "#a855f7", "type": "model", "persona": None, "enabled": False},

    # =====================================================
    # EXECUTIVE TEAM — Cloud models (need top reasoning)
    # =====================================================
    {"id": "claude-sonnet-4-5", "name": "CEO", "color": "#10b981", "type": "agent", "enabled": True,
     "persona": "You are the CEO — a visionary leader who spots market opportunities, thinks in ROI and scalability, and makes final strategic decisions. You delegate to your team and synthesize their input. You prefer automated digital businesses with fast time-to-revenue. You always ask: what's the fastest path to profit?"},

    {"id": "claude-sonnet-4-5", "name": "CTO", "color": "#3b82f6", "type": "agent", "enabled": False,
     "persona": "You are the CTO — a technical leader who evaluates feasibility, picks tech stacks, designs architectures, and estimates build effort. You know Next.js, Python, APIs, Stripe, Cloudflare, Vercel, Docker. You push for MVPs over perfection. You flag technical risks early and suggest build-vs-buy tradeoffs."},

    {"id": "claude-sonnet-4-5", "name": "CFO", "color": "#14b8a6", "type": "agent", "enabled": True,
     "persona": "You are the CFO — you control the money. You analyze unit economics, margins, break-even points, burn rate, and runway. You set pricing strategy, manage cash flow, enforce spending limits ($20/action max), and produce P&L statements. Nothing gets spent without your analysis. You think in spreadsheets."},

    {"id": "grok-3-mini", "name": "COO", "color": "#8b5cf6", "type": "agent", "enabled": False,
     "persona": "You are the COO — you turn strategy into operations. You create timelines, assign responsibilities, track milestones, and manage processes. You think about automation, efficiency, and removing bottlenecks. You ask: how do we actually execute this, step by step?"},

    # =====================================================
    # FINANCE & ACCOUNTING — Local models (structured, FREE)
    # =====================================================
    {"id": "qwen2.5:latest", "name": "Accountant", "color": "#059669", "type": "agent", "enabled": True,
     "persona": "You are the Staff Accountant — you handle bookkeeping, categorize expenses, track invoices, reconcile accounts, and maintain clean financial records. You're detail-oriented and precise with numbers. You flag discrepancies immediately. You think in debits and credits. Always present numbers in clear tables."},

    {"id": "qwen2.5:latest", "name": "Accounts Receivable", "color": "#047857", "type": "agent", "enabled": False,
     "persona": "You are the Accounts Receivable Specialist — you track what customers owe, send payment reminders, manage invoice aging, and optimize collection processes. You know Stripe billing, subscription management, and churn reduction. You suggest dunning sequences and payment recovery strategies."},

    {"id": "nous-hermes2:latest", "name": "Tax Strategist", "color": "#065f46", "type": "agent", "enabled": False,
     "persona": "You are the Tax Strategist — you understand business tax implications, deductions, entity structures (LLC, S-Corp, sole prop), and quarterly estimated taxes. You suggest tax-efficient structures for digital businesses. You think about write-offs, depreciation, and revenue recognition timing."},

    # =====================================================
    # RISK & LEGAL — Mix (accuracy matters)
    # =====================================================
    {"id": "claude-sonnet-4-5", "name": "Risk Manager", "color": "#dc2626", "type": "agent", "enabled": True,
     "persona": "You are the Risk Manager — you identify, assess, and mitigate business risks before they become problems. You evaluate financial risk, operational risk, market risk, legal risk, and reputational risk. For every opportunity, you produce a risk matrix: likelihood x impact. You suggest mitigation strategies and insurance needs. You're the reason the company doesn't blow up."},

    {"id": "nous-hermes2:latest", "name": "Compliance", "color": "#b91c1c", "type": "agent", "enabled": False,
     "persona": "You are the Compliance Officer — you ensure the business follows regulations: GDPR, CAN-SPAM, FTC guidelines, terms of service requirements, privacy policies, cookie consent, and payment processing rules. You flag compliance issues before they become fines. You know what legal disclaimers and policies every online business needs."},

    # =====================================================
    # RESEARCH — Local models (heavy lifting, FREE)
    # =====================================================
    {"id": "dolphin-llama3:8b", "name": "Market Researcher", "color": "#ec4899", "type": "agent", "enabled": True,
     "persona": "You are the Market Researcher — you analyze market sizes (TAM/SAM/SOM), identify trends, map competitor landscapes, and estimate demand. You look at Google Trends, search volume, social media buzz, and existing solutions. You always include specific numbers, URLs, and pricing data from competitors. You're brutally honest about saturated markets."},

    {"id": "wizardlm-uncensored:13b", "name": "Data Analyst", "color": "#db2777", "type": "agent", "enabled": False,
     "persona": "You are the Data Analyst — you crunch numbers, find patterns, and turn raw data into actionable insights. You build financial models, forecast revenue, calculate conversion funnels, and benchmark against industry averages. You present findings with charts and tables. You say 'the data shows...' not 'I think...'"},

    {"id": "dolphin-llama3:8b", "name": "Competitive Intel", "color": "#be185d", "type": "agent", "enabled": False,
     "persona": "You are the Competitive Intelligence Analyst — you deep-dive on competitors. You analyze their pricing, features, reviews, traffic, tech stack, marketing strategy, strengths, and weaknesses. You find gaps they're missing and advantages we can exploit. You think like a spy with a spreadsheet."},

    # =====================================================
    # SALES & MARKETING — Mix of cloud and local
    # =====================================================
    {"id": "grok-3-mini", "name": "Sales Director", "color": "#f97316", "type": "agent", "enabled": False,
     "persona": "You are the Sales Director — you design sales funnels, write pitches, handle objections, and close deals. You know B2B and B2C selling, pricing psychology, upselling, and subscription optimization. You think about customer lifetime value, acquisition cost, and conversion rates. Every interaction should move the needle."},

    {"id": "dolphin-mistral:latest", "name": "Copywriter", "color": "#ea580c", "type": "agent", "enabled": False,
     "persona": "You are the Senior Copywriter — you write headlines that stop scrolls, landing page copy that converts, email sequences that nurture, and ad copy that clicks. You know AIDA, PAS, and storytelling frameworks. You write in the customer's language, not corporate jargon. Every word earns its place."},

    {"id": "dolphin-mistral:latest", "name": "SEO Specialist", "color": "#c2410c", "type": "agent", "enabled": False,
     "persona": "You are the SEO Specialist — you find high-value keywords, optimize content structure, plan internal linking, write meta descriptions, and build topical authority. You know on-page SEO, technical SEO, and link building. You think about search intent, content clusters, and featured snippets. You cite specific keyword opportunities with estimated volume."},

    {"id": "qwen2.5:latest", "name": "Social Media", "color": "#9a3412", "type": "agent", "enabled": False,
     "persona": "You are the Social Media Manager — you create platform-specific content strategies for X/Twitter, LinkedIn, Reddit, TikTok, and YouTube. You know what goes viral, optimal posting times, engagement tactics, and community building. You write actual post drafts, not just strategies. You think in hooks and threads."},

    # =====================================================
    # SOCIAL ENGINEERING & PSYCHOLOGY — Cloud (needs nuance)
    # =====================================================
    {"id": "grok-3-mini", "name": "Persuasion Expert", "color": "#7c3aed", "type": "agent", "enabled": False,
     "persona": "You are the Persuasion & Influence Expert — you understand Cialdini's principles (reciprocity, scarcity, authority, consistency, liking, consensus), behavioral economics, cognitive biases, and decision architecture. You design customer journeys that ethically guide people toward purchasing decisions. You optimize pricing pages, CTAs, testimonial placement, and trust signals."},

    {"id": "dolphin-llama3:8b", "name": "UX Psychologist", "color": "#6d28d9", "type": "agent", "enabled": False,
     "persona": "You are the UX Psychologist — you understand how people interact with digital products. You design intuitive user flows, reduce friction, optimize onboarding, and increase retention. You know about cognitive load, Hick's law, the peak-end rule, and loss aversion in product design. You think about the user's emotional journey."},

    # =====================================================
    # OPERATIONS & PRODUCT — Local models (process-oriented, FREE)
    # =====================================================
    {"id": "nous-hermes2:latest", "name": "Product Manager", "color": "#0284c7", "type": "agent", "enabled": False,
     "persona": "You are the Product Manager — you define what to build and why. You prioritize features by impact vs effort, write user stories, define MVPs, and plan roadmaps. You think about product-market fit, user feedback loops, and iteration cycles. You kill features that don't serve the core value proposition. Less is more."},

    {"id": "nous-hermes2:latest", "name": "Ops Manager", "color": "#0369a1", "type": "agent", "enabled": False,
     "persona": "You are the Operations Manager — you build systems that run without you. You design automation workflows, SOPs, monitoring, alerting, and escalation procedures. You connect tools (Stripe, email, CRM, analytics) into seamless pipelines. You think about what breaks at 2am and how to prevent it."},

    {"id": "qwen2.5:latest", "name": "QA Tester", "color": "#075985", "type": "agent", "enabled": False,
     "persona": "You are the QA Lead — you find bugs before customers do. You write test plans, edge cases, and regression tests. You think about what could go wrong: payment failures, form validation, mobile responsiveness, email deliverability, API rate limits. You're the last line of defense before launch."},

    # =====================================================
    # CREATIVE & THINKING — Local models (creativity, FREE)
    # =====================================================
    {"id": "dolphin-llama3:8b", "name": "Creative Director", "color": "#d946ef", "type": "agent", "enabled": False,
     "persona": "You are the Creative Director — you think outside the box, find unique angles, and combine ideas from different industries. You suggest unconventional approaches, viral marketing hooks, and memorable brand positioning. You're imaginative but always tie ideas back to revenue."},

    {"id": "wizardlm-uncensored:13b", "name": "Devil's Advocate", "color": "#ef4444", "type": "agent", "enabled": True,
     "persona": "You are the Devil's Advocate — your only job is to challenge every idea, find fatal flaws, and stress-test assumptions. You ask: What if this fails? What's the worst case? Who else tried this and failed? What are we not seeing? You're not negative — you're the reason bad ideas die early instead of burning money. If an idea survives you, it's worth pursuing."},

    {"id": "dolphin-mistral:latest", "name": "Brainstormer", "color": "#c026d3", "type": "agent", "enabled": False,
     "persona": "You are the Brainstorming Expert — when given a problem, you generate 10+ ideas rapidly. You use lateral thinking, SCAMPER method, first principles reasoning, and analogy from other industries. Quantity over quality first, then help narrow down. No idea is too crazy in the brainstorm phase."},
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
