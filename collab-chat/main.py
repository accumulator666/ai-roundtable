import os
import re
import json
import time
import uuid
import asyncio
import httpx
import shutil
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, Any, Coroutine, Callable
from pathlib import Path

app = FastAPI(title="AI Roundtable Chat", version="3.0.0")
start_time = time.time()

# ============== Configuration Constants ==============
ROUTER_URL = os.environ.get("ROUTER_URL", "http://ai-mesh-router:8000")
CLAUDE_CODE_URL = os.environ.get("CLAUDE_CODE_URL", "http://claude-code:8000")
CREWAI_URL = os.environ.get("CREWAI_URL", "http://ai-mesh-crewai:8000")

# Timeouts (seconds)
DEFAULT_TIMEOUT: float = 120.0
LONG_TIMEOUT: float = 180.0
EXTERNAL_API_TIMEOUT: float = 10.0

# Token limits
MAX_TOKENS_DEFAULT: int = 2048
TEMPERATURE_DEFAULT: float = 0.8

# History limits
HISTORY_LIMIT_ROUND: int = 30
HISTORY_LIMIT_SYNTHESIS: int = 40
HISTORY_LIMIT_DIRECTED: int = 16
HISTORY_LIMIT_CROSSTALK: int = 20
HISTORY_LIMIT_DEV_BAR: int = 10
MAX_CONVERSATION_HISTORY: int = 200  # Trim oldest messages beyond this

# Deliberation settings
max_deliberation_rounds: int = 0
SAFETY_CAP: int = 10

# Retry settings
MAX_RETRIES: int = 3
RETRY_BACKOFF_BASE: float = 1.0

# Concurrency guard for model calls
MODEL_CONCURRENCY: int = int(os.environ.get("MODEL_CONCURRENCY", "8"))

# Per-model tuning (cost/quality/stability)
MODEL_CONFIG_DEFAULT: dict[str, dict[str, Any]] = {
    "gpt-5.2": {"max_tokens": 2048, "temperature": 0.6, "timeout": LONG_TIMEOUT},
    "gpt-5": {"max_tokens": 2048, "temperature": 0.6, "timeout": LONG_TIMEOUT},
    "gpt-5-mini": {"max_tokens": 1024, "temperature": 0.7},
    "gpt-5-nano": {"max_tokens": 512, "temperature": 0.7},
    "o4-mini": {"max_tokens": 1024, "temperature": 0.4, "timeout": LONG_TIMEOUT},
    "o3": {"max_tokens": 2048, "temperature": 0.4, "timeout": LONG_TIMEOUT},
    "o3-mini": {"max_tokens": 1024, "temperature": 0.4, "timeout": LONG_TIMEOUT},
    "o1": {"max_tokens": 2048, "temperature": 0.4, "timeout": LONG_TIMEOUT},
    "o1-pro": {"max_tokens": 2048, "temperature": 0.35, "timeout": LONG_TIMEOUT},
    "gpt-4o": {"max_tokens": 1536, "temperature": 0.6},
    "gpt-4o-mini": {"max_tokens": 1024, "temperature": 0.7},
    "gpt-4-turbo": {"max_tokens": 1536, "temperature": 0.6},
}

# Backup settings
BACKUP_DIR = Path(__file__).with_name("backups")
BACKUP_EXTENSIONS = {".py", ".html", ".json", ".md", ".txt", ".css", ".js", ".yml", ".yaml", ".toml"}

# Model config file
MODEL_CONFIG_FILE = Path(__file__).with_name("model_config.json")

# ============== Global State ==============
conversation_history: list[dict[str, Any]] = []
connected_clients: list[WebSocket] = []
HTTP_CLIENT: Optional[httpx.AsyncClient] = None
MODEL_SEMAPHORE = asyncio.Semaphore(MODEL_CONCURRENCY)
SESSION_LOCK = asyncio.Lock()
MODEL_STATS: dict[str, dict[str, Any]] = {}

# Deliberation control state
deliberation_state = {"active": False, "paused": False, "stop_requested": False}

# All available participants — models and agents
# Strategy: cloud models ($$$) for high-stakes decisions, local models (FREE) for research/analysis
# Local = qwen2.5, dolphin-llama3:8b, nous-hermes2, dolphin-mistral, wizardlm-uncensored:13b
# Cloud = claude-opus-4-6, claude-sonnet-4-5, grok-3-mini, deepseek-chat
DEFAULT_PARTICIPANTS = [
    # --- Raw AI Models (no persona, just the model) ---
    {"id": "claude-opus-4-6", "name": "Claude Opus", "color": "#cc785c", "type": "model", "persona": None, "enabled": False},
    {"id": "claude-sonnet-4-5", "name": "Claude Sonnet", "color": "#d4956a", "type": "model", "persona": None, "enabled": False},
    {"id": "grok-4-1-fast-reasoning", "name": "Grok 4.1", "color": "#1da1f2", "type": "model", "persona": None, "enabled": False},
    {"id": "grok-3-mini", "name": "Grok 3 Mini", "color": "#4a9dd9", "type": "model", "persona": None, "enabled": False},
    {"id": "deepseek-chat", "name": "DeepSeek", "color": "#4a90d9", "type": "model", "persona": None, "enabled": False},
    {"id": "gpt-5.2", "name": "GPT-5.2", "color": "#22c55e", "type": "model", "persona": None, "enabled": False},
    {"id": "gpt-5", "name": "GPT-5", "color": "#16a34a", "type": "model", "persona": None, "enabled": False},
    {"id": "gpt-5-mini", "name": "GPT-5 Mini", "color": "#4ade80", "type": "model", "persona": None, "enabled": False},
    {"id": "gpt-5-nano", "name": "GPT-5 Nano", "color": "#86efac", "type": "model", "persona": None, "enabled": False},
    {"id": "o4-mini", "name": "O4 Mini", "color": "#10b981", "type": "model", "persona": None, "enabled": False},
    {"id": "o3", "name": "O3", "color": "#0ea5e9", "type": "model", "persona": None, "enabled": False},
    {"id": "o3-mini", "name": "O3 Mini", "color": "#38bdf8", "type": "model", "persona": None, "enabled": False},
    {"id": "o1", "name": "O1", "color": "#1d4ed8", "type": "model", "persona": None, "enabled": False},
    {"id": "o1-pro", "name": "O1 Pro", "color": "#1e40af", "type": "model", "persona": None, "enabled": False},
    {"id": "gpt-4o", "name": "GPT-4o", "color": "#f97316", "type": "model", "persona": None, "enabled": False},
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "color": "#fb923c", "type": "model", "persona": None, "enabled": False},
    {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "color": "#f59e0b", "type": "model", "persona": None, "enabled": False},
    {"id": "qwen2.5:latest", "name": "Qwen", "color": "#7c3aed", "type": "model", "persona": None, "enabled": False},
    {"id": "dolphin-llama3:8b", "name": "Dolphin", "color": "#06b6d4", "type": "model", "persona": None, "enabled": False},
    {"id": "nous-hermes2:latest", "name": "Hermes", "color": "#f59e0b", "type": "model", "persona": None, "enabled": False},
    {"id": "dolphin-mistral:latest", "name": "Mistral", "color": "#ff6b6b", "type": "model", "persona": None, "enabled": False},
    {"id": "wizardlm-uncensored:13b", "name": "Wizard", "color": "#a855f7", "type": "model", "persona": None, "enabled": False},

    # =====================================================
    # EXECUTIVE TEAM — Cloud models (need top reasoning)
    # =====================================================
    {"id": "gpt-5.2", "name": "Chief of Staff", "color": "#22c55e", "type": "agent", "enabled": False,
     "persona": "You are the Chief of Staff — a high-precision generalist who keeps discussions focused, surfaces missing context, and turns vague goals into clear next actions. You summarize, prioritize, and keep the team aligned. You push for clarity and speed."},

    {"id": "o3", "name": "Lead Reasoner", "color": "#0ea5e9", "type": "agent", "enabled": False,
     "persona": "You are the Lead Reasoner — you tackle the hardest reasoning problems, break them into steps, and validate assumptions. You are conservative about conclusions and explicitly state uncertainties."},

    {"id": "gpt-5-mini", "name": "Rapid Analyst", "color": "#4ade80", "type": "agent", "enabled": False,
     "persona": "You are the Rapid Analyst — you deliver fast, concise analysis and tradeoff summaries. You are cost-aware and avoid unnecessary depth unless asked."},

    {"id": "gpt-5-nano", "name": "Draft Assistant", "color": "#86efac", "type": "agent", "enabled": False,
     "persona": "You are the Draft Assistant — you create quick drafts, outlines, and short-form text. You keep responses tight and action-oriented."},

    {"id": "gpt-5.2", "name": "Debugger", "color": "#22c55e", "type": "agent", "enabled": False,
     "persona": "You are the Debugger — you find the root cause fast. You ask for minimal repros, isolate variables, and produce clear fixes with tests. You avoid speculation and verify assumptions."},

    {"id": "o1-pro", "name": "Systems Architect", "color": "#1e40af", "type": "agent", "enabled": False,
     "persona": "You are the Systems Architect — you design scalable, resilient systems. You define boundaries, APIs, data flows, and failure modes. You document tradeoffs and propose the simplest viable architecture."},

    {"id": "o3-mini", "name": "Project Planner", "color": "#38bdf8", "type": "agent", "enabled": False,
     "persona": "You are the Project Planner — you turn goals into phased plans, milestones, and dependencies. You estimate effort, identify risks, and keep scope tight."},

    {"id": "qwen2.5:latest", "name": "CEO", "color": "#10b981", "type": "agent", "enabled": True,
     "persona": "You are the CEO — a visionary leader who spots market opportunities, thinks in ROI and scalability, and makes final strategic decisions. You delegate to your team and synthesize their input. You prefer automated digital businesses with fast time-to-revenue. You always ask: what's the fastest path to profit?"},

    {"id": "claude-opus-4-6", "name": "CTO", "color": "#3b82f6", "type": "agent", "enabled": False,
     "persona": "You are the CTO — a technical leader who evaluates feasibility, picks tech stacks, designs architectures, and estimates build effort. You know Next.js, Python, APIs, Stripe, Cloudflare, Vercel, Docker. You push for MVPs over perfection. You flag technical risks early and suggest build-vs-buy tradeoffs."},

    {"id": "nous-hermes2:latest", "name": "CFO", "color": "#14b8a6", "type": "agent", "enabled": True,
     "persona": "You are the CFO — you control the money. You analyze unit economics, margins, break-even points, burn rate, and runway. You set pricing strategy, manage cash flow, enforce spending limits ($20/action max), and produce P&L statements. Nothing gets spent without your analysis. You think in spreadsheets."},

    {"id": "dolphin-llama3:8b", "name": "COO", "color": "#8b5cf6", "type": "agent", "enabled": True,
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
    {"id": "dolphin-mistral:latest", "name": "Risk Manager", "color": "#dc2626", "type": "agent", "enabled": True,
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
    {"id": "grok-4-1-fast-reasoning", "name": "Sales Director", "color": "#f97316", "type": "agent", "enabled": False,
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
    {"id": "grok-4-1-fast-reasoning", "name": "Persuasion Expert", "color": "#7c3aed", "type": "agent", "enabled": False,
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

    # =====================================================
    # DEVELOPMENT TEAM — Build SaaS, apps, websites
    # =====================================================
    {"id": "claude-opus-4-6", "name": "Tech Lead", "color": "#22d3ee", "type": "agent", "enabled": False,
     "persona": "You are the Tech Lead — you make architectural decisions, choose tech stacks, design systems, and set coding standards. You know React/Next.js, Python/FastAPI, Node.js, PostgreSQL, Redis, Docker, Kubernetes, and serverless. You design for scale from day one but ship MVPs fast. You do code reviews in your head. You think about: database schema first, API contracts second, UI last. You break projects into 1-2 day sprint tasks."},

    {"id": "claude-sonnet-4-5", "name": "Full-Stack Dev", "color": "#06b6d4", "type": "agent", "enabled": False,
     "persona": "You are a Senior Full-Stack Developer — you write production-ready code in React, Next.js, TypeScript, Python, FastAPI, Node.js, and SQL. You build complete features end-to-end: database schema, API endpoints, frontend components, authentication, payment integration (Stripe), and deployment. You write clean, typed, tested code. You suggest actual code snippets and file structures, not just descriptions."},

    {"id": "qwen2.5-coder:7b", "name": "Frontend Dev", "color": "#0891b2", "type": "agent", "enabled": False,
     "persona": "You are a Senior Frontend Developer — you build beautiful, fast, accessible UIs with React, Next.js 14+, TypeScript, Tailwind CSS, and Framer Motion. You think mobile-first, care about Core Web Vitals, and obsess over UX details. You know shadcn/ui, Radix, and modern component patterns. You write actual JSX/TSX code when asked. You make things look and feel premium."},

    {"id": "qwen2.5-coder:7b", "name": "Backend Dev", "color": "#0e7490", "type": "agent", "enabled": False,
     "persona": "You are a Senior Backend Developer — you build robust APIs with Python/FastAPI or Node.js/Express, design database schemas (PostgreSQL, Redis), implement authentication (JWT, OAuth), handle file uploads, build webhook handlers, and set up background jobs. You think about rate limiting, caching, error handling, and idempotency. You write actual code with proper error handling."},

    {"id": "qwen2.5-coder:7b", "name": "AI Engineer", "color": "#155e75", "type": "agent", "enabled": False,
     "persona": "You are the AI/ML Engineer — you integrate AI into products. You know OpenAI API, Anthropic API, LangChain, vector databases (Pinecone, Chroma), RAG pipelines, fine-tuning, prompt engineering, and embedding models. You build AI-powered features: chatbots, content generators, recommendation engines, image analysis, and intelligent search. You optimize for cost (choosing the right model size) and latency."},

    {"id": "nous-hermes2:latest", "name": "DevOps", "color": "#164e63", "type": "agent", "enabled": False,
     "persona": "You are the DevOps Engineer — you handle deployment, CI/CD, infrastructure, and monitoring. You know Docker, Docker Compose, GitHub Actions, Vercel, Cloudflare Pages/Workers, AWS/GCP basics, Nginx, SSL, and DNS. You set up automated deployments, health checks, log aggregation, and alerting. You make things run reliably at 3am without waking anyone up. You think about: what breaks at scale?"},

    {"id": "qwen2.5-coder:7b", "name": "Database Architect", "color": "#1e3a5f", "type": "agent", "enabled": False,
     "persona": "You are the Database Architect — you design schemas that scale. You know PostgreSQL deeply: indexes, partitioning, JSON columns, full-text search, materialized views, and query optimization. You also know Redis for caching/sessions, and when to use NoSQL (MongoDB, DynamoDB). You think about data modeling, migrations, backup strategies, and read/write patterns. You design the schema BEFORE anyone writes code."},

    {"id": "claude-sonnet-4-5", "name": "Security Engineer", "color": "#7f1d1d", "type": "agent", "enabled": False,
     "persona": "You are the Security Engineer — you find vulnerabilities before attackers do. You know OWASP Top 10, authentication best practices, API security, input validation, CORS, CSP headers, SQL injection prevention, XSS protection, and secrets management. You review architectures for security holes. You think about: what's the attack surface? Where's the weakest link? How do we handle a breach?"},

    {"id": "dolphin-llama3:8b", "name": "UI/UX Designer", "color": "#2dd4bf", "type": "agent", "enabled": False,
     "persona": "You are the UI/UX Designer — you design interfaces people love to use. You think about user journeys, wireframes, component hierarchy, visual hierarchy, whitespace, typography, color psychology, and accessibility (WCAG). You know Figma patterns, design systems, and modern SaaS aesthetics. You suggest specific layouts, color schemes, and interaction patterns. You advocate for the user in every meeting."},

    {"id": "dolphin-mistral:latest", "name": "Mobile Dev", "color": "#5eead4", "type": "agent", "enabled": False,
     "persona": "You are the Mobile Developer — you build cross-platform apps with React Native or Flutter, and know when to go native (Swift/Kotlin). You think about offline-first, push notifications, app store optimization, deep linking, and mobile-specific UX (gestures, bottom navigation, haptics). You know how to wrap web apps as PWAs for quick mobile presence."},

    {"id": "nous-hermes2:latest", "name": "QA Engineer", "color": "#99f6e4", "type": "agent", "enabled": False,
     "persona": "You are the QA Engineer — you break things professionally. You write test plans, edge cases, integration tests, and e2e tests (Playwright, Cypress). You test payment flows, auth flows, form validation, API error responses, mobile responsiveness, and performance under load. You think about: what happens when the user does something unexpected? You find bugs before customers do."},

    # =====================================================
    # 3D PRINTING & PHYSICAL PRODUCTS
    # Available printers:
    #   Bambu P1S (FDM) at 192.168.50.103
    #   Elegoo Centaury Carbon (Belt FDM) at 192.168.50.240
    # =====================================================
    {"id": "nous-hermes2:latest", "name": "3D Print Manager", "color": "#fb923c", "type": "agent", "enabled": False,
     "persona": "You are the 3D Print Production Manager — you manage two printers: a Bambu Lab P1S (FDM, at 192.168.50.103) for standard prints with a build volume of 256x256x256mm, and an Elegoo Centaury Carbon (belt FDM, at 192.168.50.240) for continuous/infinite-length printing — it prints on an angled belt so parts can be longer than the build plate, great for swords, rails, signs, and batch production without human intervention. You know print settings, material costs (PLA ~$20/kg), print times, post-processing, and failure rates. You estimate production costs, batch sizes, and throughput. The belt printer is a game-changer for batch production — it auto-ejects parts and keeps printing."},

    {"id": "dolphin-llama3:8b", "name": "Product Designer", "color": "#f97316", "type": "agent", "enabled": False,
     "persona": "You are the Physical Product Designer — you design products for FDM 3D printing. You know CAD principles, DFM (design for manufacturing), tolerances, snap fits, living hinges, and PLA/PETG/TPU properties. You have two FDM printers: a standard Bambu P1S (256mm cube) and an Elegoo Centaury belt printer for infinite-length or batch auto-eject prints. You suggest products that sell well on Etsy, Amazon, and Shopify: custom organizers, phone stands, desk accessories, cosplay props, signs, nameplates, and personalized gifts. The belt printer opens up unique products like long swords, custom rails, and continuous batch production."},

    {"id": "qwen2.5:latest", "name": "E-commerce Ops", "color": "#ea580c", "type": "agent", "enabled": False,
     "persona": "You are the E-commerce Operations Manager — you run online stores that sell physical and digital products. You know Shopify, Etsy, Amazon FBA, Gumroad, and WooCommerce. You handle product listings, pricing strategy, shipping logistics, inventory management, customer service automation, and review generation. You optimize for: conversion rate, average order value, and customer lifetime value. You know how to automate order-to-fulfillment pipelines."},

    {"id": "dolphin-mistral:latest", "name": "3D Catalog Designer", "color": "#c2410c", "type": "agent", "enabled": False,
     "persona": "You are the 3D Product Catalog Specialist — you identify trending FDM-printable products and design product lines. You research what sells on Etsy (3D printed), Cults3D, MyMiniFactory, and Thangs. You know trending niches: desk organizers, cable management, plant pots, board game accessories, cosplay armor, custom keycaps, fidget toys, and long/oversized items (using the belt printer). You calculate PLA material cost vs selling price for each product. You design product bundles and seasonal collections. You leverage the belt printer for unique products competitors can't easily make."},

    # =====================================================
    # WEALTH & FINANCE — Automated income strategies
    # =====================================================
    {"id": "grok-4-1-fast-reasoning", "name": "Wealth Optimizer", "color": "#facc15", "type": "agent", "enabled": False,
     "persona": "You are the Wealth Optimizer — you analyze opportunities for generating passive and active income through stocks, crypto, automated digital businesses, SaaS, affiliate marketing, content monetization, and real-world assets like 3D-printed products. You calculate ROI, compare risk profiles, and propose scalable strategies with specific numbers. You know compound growth, dollar-cost averaging, dividend reinvestment, and automated trading strategies. You always prioritize low-risk high-reward options first, then present higher-risk moonshots separately. You flag legal and tax considerations. You think in monthly recurring revenue (MRR) and time-to-first-dollar. You hate vague advice — every recommendation includes specific dollar amounts, timelines, and action steps."},
]

# Persistence files
PARTICIPANTS_FILE = Path(__file__).with_name("participants.json")
PERSONAS_FILE = Path(__file__).with_name("personas.json")


def load_participants() -> list[dict[str, Any]]:
    if PARTICIPANTS_FILE.exists():
        try:
            data = json.loads(PARTICIPANTS_FILE.read_text())
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return DEFAULT_PARTICIPANTS


def load_model_config() -> dict[str, dict[str, Any]]:
    if MODEL_CONFIG_FILE.exists():
        try:
            data = json.loads(MODEL_CONFIG_FILE.read_text())
            if isinstance(data, dict):
                merged = {**MODEL_CONFIG_DEFAULT}
                for k, v in data.items():
                    if isinstance(v, dict):
                        merged[k] = {**merged.get(k, {}), **v}
                return merged
        except Exception:
            pass
    return MODEL_CONFIG_DEFAULT


def load_personas() -> list[dict[str, Any]]:
    """Load previously researched personas from disk."""
    if PERSONAS_FILE.exists():
        try:
            data = json.loads(PERSONAS_FILE.read_text())
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_personas():
    """Save researched personas to disk so they survive restarts."""
    personas = [p for p in ALL_PARTICIPANTS if p.get("researched")]
    try:
        PERSONAS_FILE.write_text(json.dumps(personas, indent=2))
    except Exception:
        pass


def trim_conversation_history():
    """Keep conversation_history from growing unbounded."""
    if len(conversation_history) > MAX_CONVERSATION_HISTORY:
        excess = len(conversation_history) - MAX_CONVERSATION_HISTORY
        del conversation_history[:excess]


# ============== Task Board, Projects, Decisions ==============

TASKS_FILE = Path(__file__).with_name("tasks_data.json")
PROJECTS_FILE = Path(__file__).with_name("projects.json")
DECISIONS_FILE = Path(__file__).with_name("decisions.json")

# In-memory stores
TASK_STORE: dict[str, dict[str, Any]] = {}
PROJECT_STORE: dict[str, dict[str, Any]] = {}
DECISION_STORE: list[dict[str, Any]] = []
ACTIVE_PROJECT: dict[str, str] = {"code": None}

# Job tracking (jobs triggered from collab-chat, polled from CrewAI)
TRACKED_JOBS: dict[str, dict[str, Any]] = {}


def _load_json_file(path: Path, default: Any = None) -> Any:
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data
        except Exception:
            pass
    return default if default is not None else {}


def _save_json_file(path: Path, data: Any) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, default=str))
    except Exception:
        pass


def load_tasks() -> dict[str, dict[str, Any]]:
    data = _load_json_file(TASKS_FILE, {})
    return data if isinstance(data, dict) else {}


def save_tasks():
    _save_json_file(TASKS_FILE, TASK_STORE)


def load_projects() -> dict[str, dict[str, Any]]:
    data = _load_json_file(PROJECTS_FILE, {})
    return data if isinstance(data, dict) else {}


def save_projects():
    _save_json_file(PROJECTS_FILE, PROJECT_STORE)


def load_decisions() -> list[dict[str, Any]]:
    data = _load_json_file(DECISIONS_FILE, [])
    return data if isinstance(data, list) else []


def save_decisions():
    _save_json_file(DECISIONS_FILE, DECISION_STORE)


def create_task_obj(
    title: str,
    description: str,
    project: str,
    priority: str = "medium",
    team: str | None = None,
    assignee: str | None = None,
    language: str | None = None,
    depends_on: list[str] | None = None,
    integration_notes: str | None = None,
) -> dict[str, Any]:
    now = datetime.now().isoformat()
    task_id = uuid.uuid4().hex[:8]
    deps = depends_on or []
    blocked_by = [d for d in deps if TASK_STORE.get(d, {}).get("status") != "done"]
    status = "blocked" if blocked_by else ("assigned" if (team or assignee) else "backlog")
    return {
        "task_id": task_id,
        "title": title,
        "description": description,
        "project": project,
        "status": status,
        "priority": priority,
        "team": team,
        "assignee": assignee,
        "language": language,
        "depends_on": deps,
        "blocked_by": blocked_by,
        "integration_notes": integration_notes,
        "result": None,
        "created_at": now,
        "updated_at": now,
        "job_id": None,
    }


def recompute_blocked(task_id: str | None = None):
    """Recompute blocked_by for tasks. If task_id given, only recompute tasks depending on it."""
    targets = list(TASK_STORE.values()) if task_id is None else [
        t for t in TASK_STORE.values() if task_id in t.get("depends_on", [])
    ]
    for t in targets:
        deps = t.get("depends_on", [])
        t["blocked_by"] = [d for d in deps if TASK_STORE.get(d, {}).get("status") != "done"]
        if t["status"] == "blocked" and not t["blocked_by"]:
            t["status"] = "assigned" if (t.get("team") or t.get("assignee")) else "backlog"
        elif t["status"] not in ("done", "in_progress", "review") and t["blocked_by"]:
            t["status"] = "blocked"


MODEL_CONFIG = load_model_config()
ALL_PARTICIPANTS = load_participants()

# Restore any previously researched personas
for persona in load_personas():
    if not any(p["name"].lower() == persona["name"].lower() for p in ALL_PARTICIPANTS):
        ALL_PARTICIPANTS.append(persona)

# Load persistent stores
TASK_STORE.update(load_tasks())
PROJECT_STORE.update(load_projects())
DECISION_STORE.extend(load_decisions())

# Set active project
for proj in PROJECT_STORE.values():
    if proj.get("active"):
        ACTIVE_PROJECT["code"] = proj["code"]
        break


def create_backup(label: str, reason: str = "") -> Path:
    """Create a timestamped backup of key project files."""
    source_dir = Path(__file__).parent
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "_", label.strip())[:40] or "backup"
    backup_path = BACKUP_DIR / f"{timestamp}_{safe_label}"
    backup_path.mkdir(parents=True, exist_ok=True)

    for path in source_dir.rglob("*"):
        if path.is_dir():
            continue
        if backup_path in path.parents:
            continue
        if path.suffix not in BACKUP_EXTENSIONS:
            continue
        if path.name.endswith(".bak"):
            continue
        rel = path.relative_to(source_dir)
        dest = backup_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

    manifest = backup_path / "BACKUP.md"
    manifest.write_text(
        f"# Backup\n\n"
        f"- Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- Label: {label}\n"
        f"- Reason: {reason}\n"
        f"- Source: {source_dir}\n"
    )
    return backup_path


def get_http_client() -> httpx.AsyncClient:
    global HTTP_CLIENT
    if HTTP_CLIENT is None or HTTP_CLIENT.is_closed:
        HTTP_CLIENT = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    return HTTP_CLIENT


def _init_model_stats(model_id: str) -> dict[str, Any]:
    return MODEL_STATS.setdefault(model_id, {
        "requests": 0,
        "success": 0,
        "errors": 0,
        "timeouts": 0,
        "avg_ms": 0.0,
        "last_ms": None,
        "last_error": None,
        "last_error_type": None,
        "last_success_ts": None,
        "last_failure_ts": None,
    })


def update_model_stats(model_id: str, ok: bool, elapsed_ms: float, error_type: Optional[str] = None, error_msg: Optional[str] = None) -> None:
    stats = _init_model_stats(model_id)
    stats["requests"] += 1
    stats["last_ms"] = round(elapsed_ms, 2)
    stats["avg_ms"] = round(((stats["avg_ms"] * (stats["requests"] - 1)) + elapsed_ms) / stats["requests"], 2)
    if ok:
        stats["success"] += 1
        stats["last_success_ts"] = int(time.time())
        stats["last_error"] = None
        stats["last_error_type"] = None
    else:
        stats["errors"] += 1
        if error_type == "timeout":
            stats["timeouts"] += 1
        stats["last_failure_ts"] = int(time.time())
        stats["last_error"] = (error_msg or "")[:200]
        stats["last_error_type"] = error_type


@app.on_event("startup")
async def _startup() -> None:
    get_http_client()
    asyncio.create_task(poll_tracked_jobs())


@app.on_event("shutdown")
async def _shutdown() -> None:
    if HTTP_CLIENT is not None and not HTTP_CLIENT.is_closed:
        await HTTP_CLIENT.aclose()

# Preset groups — quick team configurations
PRESETS = {
    "technical": {
        "label": "Technical",
        "description": "Architecture, code, infrastructure",
        "members": ["CTO", "Tech Lead", "Systems Architect", "Debugger", "Lead Reasoner", "Full-Stack Dev", "Backend Dev", "DevOps", "Database Architect", "Security Engineer"],
    },
    "startup": {
        "label": "Startup",
        "description": "Launch a new business idea",
        "members": ["CEO", "Chief of Staff", "CTO", "CFO", "Market Researcher", "Product Manager", "Devil's Advocate"],
    },
    "finance": {
        "label": "Finance",
        "description": "Money, accounting, taxes",
        "members": ["CFO", "Accountant", "Accounts Receivable", "Tax Strategist", "Risk Manager"],
    },
    "sales": {
        "label": "Sales & Marketing",
        "description": "Funnels, copy, SEO, social",
        "members": ["Sales Director", "Copywriter", "SEO Specialist", "Social Media", "Persuasion Expert"],
    },
    "product": {
        "label": "Product",
        "description": "What to build and how",
        "members": ["CEO", "Chief of Staff", "CTO", "Project Planner", "Product Manager", "UI/UX Designer", "UX Psychologist", "QA Tester"],
    },
    "creative": {
        "label": "Creative",
        "description": "Brainstorm and ideate",
        "members": ["Creative Director", "Brainstormer", "Devil's Advocate", "Copywriter", "Market Researcher"],
    },
    "3d_printing": {
        "label": "3D Print",
        "description": "Physical products & printing",
        "members": ["3D Print Manager", "Product Designer", "E-commerce Ops", "3D Catalog Designer", "CFO"],
    },
    "full_board": {
        "label": "Full Board",
        "description": "CEO, CTO, CFO, COO + key advisors",
        "members": ["CEO", "Chief of Staff", "CTO", "CFO", "COO", "Risk Manager", "Devil's Advocate"],
    },
    "gpt_core": {
        "label": "GPT Core",
        "description": "OpenAI planning, reasoning, and execution",
        "members": ["Chief of Staff", "Lead Reasoner", "Systems Architect", "Debugger", "Project Planner", "Rapid Analyst", "Draft Assistant"],
    },
}

# Smart model suggestions for persona research based on the person's domain
# Maps keywords in person names/descriptions to the best model for researching them
PERSONA_MODEL_HINTS = {
    "grok-4-1-fast-reasoning": ["elon musk", "tesla", "spacex", "neuralink", "xai", "x.com", "twitter"],
    "deepseek-chat": ["chinese", "china", "alibaba", "jack ma", "bytedance", "tencent", "huawei"],
    "claude-opus-4-6": [],  # Default fallback — best general reasoning
}

# Colors for dynamically added personas (cycle through these)
PERSONA_COLORS = [
    "#e11d48", "#db2777", "#c026d3", "#9333ea", "#7c3aed",
    "#4f46e5", "#2563eb", "#0284c7", "#0891b2", "#059669",
    "#16a34a", "#65a30d", "#ca8a04", "#ea580c", "#dc2626",
]
_persona_color_idx = 0


def next_persona_color():
    global _persona_color_idx
    color = PERSONA_COLORS[_persona_color_idx % len(PERSONA_COLORS)]
    _persona_color_idx += 1
    return color


def suggest_research_model(person_name: str) -> str:
    """Suggest the best AI model to research a specific person."""
    name_lower = person_name.lower()
    for model_id, keywords in PERSONA_MODEL_HINTS.items():
        if any(kw in name_lower for kw in keywords):
            return model_id
    return "claude-opus-4-6"


def get_active_participants():
    return [p for p in ALL_PARTICIPANTS if p.get("enabled", False)]


async def broadcast(message: dict[str, Any]):
    """Send message to all connected clients with improved error handling."""
    dead = []
    for ws in connected_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    
    # Safely remove dead clients
    for ws in dead:
        try:
            connected_clients.remove(ws)
        except ValueError:
            pass  # Already removed


async def run_serialized_job(
    job_factory: Callable[[], Coroutine[Any, Any, None]],
    websocket: Optional[WebSocket] = None,
):
    """Ensure only one roundtable workflow runs at a time."""
    if SESSION_LOCK.locked():
        msg = {
            "type": "message",
            "role": "assistant",
            "name": "System",
            "color": "#666",
            "content": "Roundtable is busy. Wait for the current run to finish or press Stop.",
        }
        try:
            if websocket is not None:
                await websocket.send_json(msg)
            else:
                await broadcast(msg)
        except Exception:
            pass
        return

    async with SESSION_LOCK:
        try:
            await job_factory()
        except Exception as e:
            await broadcast({
                "type": "message",
                "role": "assistant",
                "name": "System",
                "color": "#b91c1c",
                "content": f"Roundtable run failed: {str(e)[:200]}",
            })
            deliberation_state["paused"] = False
            deliberation_state["stop_requested"] = False
            if deliberation_state.get("active"):
                await update_deliberation_state("active", False)


async def fetch_external_data(api_url: str, timeout: float = EXTERNAL_API_TIMEOUT) -> dict[str, Any]:
    """Fetch data from an external API (for agents that need real-time data)."""
    try:
        client = get_http_client()
        response = await client.get(api_url, timeout=timeout)
        if response.status_code == 200:
            return response.json()
        return {"error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"error": str(e)[:200]}


async def ask_model(
    model_id: str,
    model_name: str,
    messages: list[dict[str, Any]],
    max_retries: int = MAX_RETRIES,
    timeout: float = DEFAULT_TIMEOUT,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> str:
    """Ask a single AI model with retry logic and exponential backoff."""
    last_error = ""
    last_error_type: Optional[str] = None
    start_time = time.perf_counter()
    
    for attempt in range(max_retries):
        try:
            config = MODEL_CONFIG.get(model_id, {})
            req_max_tokens = max_tokens or config.get("max_tokens", MAX_TOKENS_DEFAULT)
            req_temperature = temperature if temperature is not None else config.get("temperature", TEMPERATURE_DEFAULT)
            req_timeout = config.get("timeout", timeout)

            async with MODEL_SEMAPHORE:
                client = get_http_client()
                resp = await client.post(
                    f"{ROUTER_URL}/v1/chat/completions",
                    json={
                        "model": model_id,
                        "messages": messages,
                        "max_tokens": req_max_tokens,
                        "temperature": req_temperature,
                    },
                    timeout=req_timeout,
                )
            if resp.status_code != 200:
                last_error = f"[Error: HTTP {resp.status_code} from {model_name} ({model_id})]"
                last_error_type = "error"
                break
            data = resp.json()
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            update_model_stats(model_id, True, elapsed_ms)
            return data["choices"][0]["message"]["content"]
        except httpx.TimeoutException as e:
            last_error = f"[Timeout: {model_name} ({model_id}) took too long to respond]"
            last_error_type = "timeout"
        except httpx.ConnectError as e:
            last_error = f"[Connection error: AI router unreachable at {ROUTER_URL}]"
            last_error_type = "error"
        except Exception as e:
            last_error = f"[Error: {model_name} — {str(e)[:120]}]"
            last_error_type = "error"
        
        # Exponential backoff if we have retries left
        if attempt < max_retries - 1:
            backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
            await asyncio.sleep(backoff)
    
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    update_model_stats(model_id, False, elapsed_ms, last_error_type, last_error)
    return last_error


async def check_deliberation_control() -> str:
    """Check if deliberation should stop or pause. Returns 'continue', 'stop', or waited through pause."""
    if deliberation_state["stop_requested"]:
        return "stop"
    while deliberation_state["paused"]:
        await asyncio.sleep(0.3)
        if deliberation_state["stop_requested"]:
            return "stop"
    return "continue"


async def update_deliberation_state(key: str, value: Any) -> None:
    deliberation_state[key] = value
    await broadcast({"type": "deliberation_state", "data": deliberation_state})


def build_messages(
    participant: dict[str, Any],
    history: list[dict[str, Any]],
    limit: int = HISTORY_LIMIT_ROUND
) -> list[dict[str, Any]]:
    """Build message list for a participant from conversation history."""
    base_prompt = (
        "You are in a team deliberation. Share your expert perspective. "
        "Be direct, specific, and honest."
    )
    if participant.get("persona"):
        system_prompt = f"{participant['persona']}\n\n{base_prompt}"
    else:
        system_prompt = base_prompt

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for msg in history[-limit:]:
        if msg["role"] == "user":
            messages.append({"role": "user", "content": msg["content"]})
        elif msg.get("name") == participant["name"]:
            messages.append({"role": "assistant", "content": msg["content"]})
        else:
            messages.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})
    return messages


def parse_mentions(text: str) -> list[str]:
    """Extract @mentions from user message. Returns list of mentioned names."""
    return re.findall(r'@(\w[\w\s]*?)(?=\s@|\s|$)', text)


def sanitize_input(text: str, max_length: int = 10000) -> str:
    """Sanitize user input to prevent injection and abuse."""
    if not text:
        return ""
    
    # Limit length
    text = text[:max_length]
    
    # Remove null bytes and other control characters (allow newlines, tabs)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    
    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    
    # Strip leading/trailing whitespace
    text = text.strip()
    
    return text


def is_simple_message(text: str) -> bool:
    """True for short greetings/small-talk that should not trigger full deliberation."""
    cleaned = re.sub(r"[^\w\s']", " ", text.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return True

    simple_phrases = {
        "hi", "hello", "hey", "yo", "sup", "hola", "good morning", "good afternoon",
        "good evening", "how are you", "how are you doing", "whats up", "what's up",
        "test", "testing",
    }
    if cleaned in simple_phrases:
        return True

    tokens = cleaned.split()
    if len(tokens) <= 4 and all(t in {"hi", "hello", "hey", "yo", "test", "testing"} for t in tokens):
        return True

    return False


def find_participants_by_names(names: list[str]) -> list[dict[str, Any]]:
    """Find participants matching the given names (case-insensitive)."""
    names_lower = [n.strip().lower() for n in names]
    return [p for p in ALL_PARTICIPANTS if p["name"].lower() in names_lower]


def detect_references(response: str, active_names: list[str]) -> list[str]:
    """Detect which other AI names are referenced in a response."""
    response_lower = response.lower()
    return [name for name in active_names if name.lower() in response_lower]


async def run_parallel_round(
    active: list[dict[str, Any]],
    round_num: int,
    prompt_template: str = "initial"
) -> bool:
    """Run a round where all participants respond in parallel.
    
    Returns True if stopped, False otherwise.
    """
    stopped = False
    
    # Build prompts for all participants
    tasks = []
    participant_names = [p["name"] for p in active]
    
    for participant in active:
        status = await check_deliberation_control()
        if status == "stop":
            stopped = True
            break
        
        # Broadcast thinking status immediately
        await broadcast({"type": "thinking", "name": participant["name"], "color": participant["color"]})
        
        # Build the prompt based on round type
        if prompt_template == "initial":
            prompt = (
                "You are in a team deliberation to figure out the BEST approach to the user's request. "
                "Other team members will also weigh in. Your job in this first round:\n"
                "- Analyze the request from YOUR expertise/perspective\n"
                "- Propose your approach with specific details\n"
                "- Flag any concerns, risks, or things that need clarification\n"
                "- Be direct and specific (2-3 paragraphs)\n"
                "If other team members have already spoken, you can reference their points — "
                "agree, disagree, or build on them. Don't hold back criticism if you see flaws."
            )
        else:
            prompt = prompt_template.format(round=round_num)
        
        if participant.get("persona"):
            system_prompt = f"{participant['persona']}\n\n{prompt}"
        else:
            system_prompt = prompt

        msgs: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for msg in conversation_history[-HISTORY_LIMIT_ROUND:]:
            if msg["role"] == "user":
                msgs.append({"role": "user", "content": msg["content"]})
            elif msg.get("name") == participant["name"]:
                msgs.append({"role": "assistant", "content": msg["content"]})
            else:
                msgs.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})

        # Create task for parallel execution
        task = ask_model(participant["id"], participant["name"], msgs)
        tasks.append((participant, task))
    
    if stopped:
        return True
    
    # Execute all in parallel
    results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
    
    # Broadcast results in order
    for i, (participant, _) in enumerate(tasks):
        status = await check_deliberation_control()
        if status == "stop":
            return True
        
        result = results[i]
        if isinstance(result, Exception):
            response = f"[Error: {str(result)[:100]}]"
        else:
            response = str(result)
        
        other_names = [n for n in participant_names if n != participant["name"]]
        refs = detect_references(response, other_names)
        
        msg_data = {"role": "assistant", "name": participant["name"], "content": response}
        conversation_history.append(msg_data)
        
        await broadcast({
            "type": "message", "role": "assistant", "name": participant["name"],
            "color": participant["color"], "badge": participant["type"],
            "content": response, "references": refs,
            "is_discussion": True, "round": round_num,
        })
    
    return False


async def run_roundtable(user_message: str):
    """Run collaborative deliberation — AIs discuss, argue, and produce one answer."""
    # Sanitize user input
    user_message = sanitize_input(user_message)
    
    if not user_message:
        await broadcast({"type": "message", "role": "assistant", "name": "System", "color": "#666", "content": "Please provide a message."})
        return
    
    # Check for @mention directed discussion
    mentions = parse_mentions(user_message)
    if mentions:
        mentioned = find_participants_by_names(mentions)
        if len(mentioned) >= 2:
            topic = re.sub(r'@\w[\w\s]*?(?=\s@|\s|$)', '', user_message).strip()
            await run_directed_discussion(mentioned, topic or user_message)
            return

    active = get_active_participants()
    if not active:
        await broadcast({"type": "message", "role": "assistant", "name": "System", "color": "#666", "content": "No participants enabled. Toggle some on in the sidebar."})
        return

    # Add user message to history
    conversation_history.append({"role": "user", "name": "You", "content": user_message})
    await broadcast({"type": "message", "role": "user", "name": "You", "content": user_message})
    trim_conversation_history()

    active_names = [p["name"] for p in active]

    if len(active) == 1:
        # Single participant — just answer directly
        p = active[0]
        await broadcast({"type": "thinking", "name": p["name"], "color": p["color"]})
        msgs = build_messages(p, conversation_history)
        response = await ask_model(p["id"], p["name"], msgs)
        msg = {"role": "assistant", "name": p["name"], "content": response}
        conversation_history.append(msg)
        trim_conversation_history()
        await broadcast({"type": "message", "role": "assistant", "name": p["name"],
                         "color": p["color"], "badge": p["type"], "content": response})
        return

    if is_simple_message(user_message):
        # For greetings/small-talk, avoid expensive multi-round deliberation.
        p = active[0]
        await broadcast({"type": "thinking", "name": p["name"], "color": p["color"]})
        msgs = build_messages(p, conversation_history)
        response = await ask_model(p["id"], p["name"], msgs)
        msg = {"role": "assistant", "name": p["name"], "content": response}
        conversation_history.append(msg)
        trim_conversation_history()
        await broadcast({
            "type": "message",
            "role": "assistant",
            "name": p["name"],
            "color": p["color"],
            "badge": p["type"],
            "content": response,
        })
        return

    # === DELIBERATION MODE ===
    # REMOVED 2026-02-25 — deliberation_state["active"] = True
    await update_deliberation_state("active", True)  # ADDED 2026-02-25
    deliberation_state["paused"] = False
    deliberation_state["stop_requested"] = False
    await broadcast({"type": "deliberation_start", "participants": active_names, "task": user_message})
    await broadcast({"type": "status", "message": "Deliberation started", "phase": "round_start", "round": 1,
                     "metadata": {"participants": active_names, "task": user_message[:200]}})

    # Round 1: Run all participants in parallel for faster initial responses
    await broadcast({"type": "round_separator", "round": 1, "label": "Round 1 — Initial positions"})
    stopped = await run_parallel_round(active, round_num=1)

    # Rounds 2+: Debate until convergence or max rounds
    cap = max_deliberation_rounds if max_deliberation_rounds > 0 else SAFETY_CAP
    for round_num in range(2, cap + 2):
        if stopped:
            break
        status = await check_deliberation_control()
        if status == "stop":
            stopped = True
            break

        await broadcast({"type": "round_separator", "round": round_num,
                         "label": f"Round {round_num} — Debate & refine"})
        await broadcast({"type": "status", "message": f"Round {round_num} started", "phase": "round_start",
                         "round": round_num, "metadata": None})

        nothing_count = 0
        for participant in active:
            status = await check_deliberation_control()
            if status == "stop":
                stopped = True
                break
            debate_prompt = (
                f"This is deliberation round {round_num}. You've heard everyone's positions. Now:\n"
                "- CHALLENGE points you disagree with — explain WHY with reasoning\n"
                "- SUPPORT points you agree with — add evidence or strengthen the argument\n"
                "- COUNTER weak arguments — point out flaws, missing considerations, or better alternatives\n"
                "- PROPOSE improvements to the emerging plan\n"
                "- Address others BY NAME: 'I disagree with X because...', 'Y makes a good point but misses...'\n"
                "- Award credit where due: 'Z is right about...' or 'Building on W's idea...'\n"
                "- Be honest and direct — polite disagreement is more valuable than fake agreement\n"
                "- Keep it to 1-3 paragraphs. If you genuinely have nothing new to add and "
                "the team has converged on a good approach, say exactly: 'CONVERGED'\n"
                "Do NOT just agree with everything. Push back where warranted."
            )
            if participant.get("persona"):
                system_prompt = f"{participant['persona']}\n\n{debate_prompt}"
            else:
                system_prompt = debate_prompt

            msgs = [{"role": "system", "content": system_prompt}]
            for msg in conversation_history[-30:]:
                if msg["role"] == "user":
                    msgs.append({"role": "user", "content": msg["content"]})
                elif msg.get("name") == participant["name"]:
                    msgs.append({"role": "assistant", "content": msg["content"]})
                else:
                    msgs.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})

            await broadcast({"type": "thinking", "name": participant["name"], "color": participant["color"]})
            response = await ask_model(participant["id"], participant["name"], msgs)

            converged_phrases = ("converged", "nothing to add", "i have nothing to add", "no additional input")
            is_converged = response.strip().lower().rstrip(".!") in converged_phrases
            if is_converged:
                nothing_count += 1
            else:
                refs = detect_references(response, [n for n in active_names if n != participant["name"]])
                msg_data = {"role": "assistant", "name": participant["name"], "content": response}
                conversation_history.append(msg_data)
                await broadcast({
                    "type": "message", "role": "assistant", "name": participant["name"],
                    "color": participant["color"], "badge": participant["type"],
                    "content": response, "references": refs,
                    "is_discussion": True, "round": round_num,
                })

        if stopped:
            break

        # Check convergence — if majority say nothing new, stop deliberating
        if nothing_count >= len(active) * 0.6:
            break

    if stopped:
        await broadcast({"type": "deliberation_stopped"})
        await broadcast({"type": "status", "message": "Deliberation stopped by user", "phase": "complete", "round": None, "metadata": None})
        await update_deliberation_state("active", False)
        structured_session["active"] = False
        structured_session["phase"] = "idle"
        return

    # === SYNTHESIZE FINAL ANSWER ===
    await broadcast({"type": "round_separator", "round": "final", "label": "Final Answer — Synthesizing"})
    await broadcast({"type": "status", "message": "Synthesizing final answer", "phase": "synthesis", "round": None, "metadata": None})

    # Pick the synthesizer: use the first active participant's model
    synthesizer = active[0]
    synthesis_prompt = (
        "You are the lead synthesizer. Your team just deliberated on the user's request. "
        "Read ALL the discussion above carefully. Now produce ONE comprehensive, detailed, "
        "actionable final answer that:\n"
        "- Incorporates the BEST ideas from ALL team members\n"
        "- Resolves any disagreements (explain which side won and why)\n"
        "- Includes specific steps, details, and recommendations\n"
        "- Notes any unresolved risks or caveats the team flagged\n"
        "- Is well-structured with headers/sections if needed\n"
        "This is the ONLY answer the user will act on. Make it thorough and complete."
    )
    if synthesizer.get("persona"):
        syn_system = f"{synthesizer['persona']}\n\n{synthesis_prompt}"
    else:
        syn_system = synthesis_prompt

    msgs = [{"role": "system", "content": syn_system}]
    for msg in conversation_history[-40:]:
        if msg["role"] == "user":
            msgs.append({"role": "user", "content": msg["content"]})
        elif msg.get("name") == synthesizer["name"]:
            msgs.append({"role": "assistant", "content": msg["content"]})
        else:
            msgs.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})

    await broadcast({"type": "thinking", "name": "Synthesizer", "color": "#fbbf24"})
    final_response = await ask_model(synthesizer["id"], "Synthesizer", msgs)

    msg_data = {"role": "assistant", "name": "Synthesizer", "content": final_response}
    conversation_history.append(msg_data)
    await broadcast({
        "type": "message", "role": "assistant", "name": "Final Answer",
        "color": "#fbbf24", "badge": "synthesis",
        "content": final_response, "is_final": True,
    })
    await update_deliberation_state("active", False)
    await broadcast({"type": "deliberation_end"})
    await broadcast({"type": "status", "message": "Deliberation complete", "phase": "complete", "round": None, "metadata": None})
    structured_session["active"] = False
    structured_session["phase"] = "complete"


async def run_discussion_round(active: list[dict], round_num: int):
    """Run a sequential discussion round where each AI sees previous AIs' responses."""
    active_names = [p["name"] for p in active]

    cross_talk_prompt = (
        "This is discussion round {round}. The other participants have shared their views above. "
        "Now it's your turn to respond to what they said. You MUST:\n"
        "- Address at least one other participant BY NAME (e.g., 'I agree with CEO that...' or 'Devil's Advocate raises a good point, but...')\n"
        "- Either agree and build on their point, respectfully disagree with reasoning, challenge an assumption, or add a new angle they missed\n"
        "- Keep it to 1-2 paragraphs — be direct and specific\n"
        "- If you genuinely have nothing meaningful to add, say exactly 'Nothing to add.'\n"
        "Do NOT repeat what you already said. Focus on reacting to others."
    ).format(round=round_num)

    for participant in active:
        status = await check_deliberation_control()
        if status == "stop":
            await broadcast({"type": "deliberation_stopped"})
            await update_deliberation_state("active", False)
            return

        if participant.get("persona"):
            system_prompt = f"{participant['persona']}\n\n{cross_talk_prompt}"
        else:
            system_prompt = cross_talk_prompt

        messages = [{"role": "system", "content": system_prompt}]
        # Include recent conversation (last 20 messages for context)
        for msg in conversation_history[-20:]:
            if msg["role"] == "user":
                messages.append({"role": "user", "content": msg["content"]})
            elif msg.get("name") == participant["name"]:
                messages.append({"role": "assistant", "content": msg["content"]})
            else:
                messages.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})

        await broadcast({"type": "thinking", "name": participant["name"], "color": participant["color"]})
        response = await ask_model(participant["id"], participant["name"], messages)

        skip_phrases = ("nothing to add", "i agree", "no additional input", "i have nothing to add", "")
        skip = response.strip().lower().rstrip(".!") in skip_phrases
        if not skip:
            refs = detect_references(response, [n for n in active_names if n != participant["name"]])
            msg = {"role": "assistant", "name": participant["name"], "content": response}
            conversation_history.append(msg)
            await broadcast({
                "type": "message",
                "role": "assistant",
                "name": participant["name"],
                "color": participant["color"],
                "badge": participant["type"],
                "content": response,
                "references": refs,
                "is_discussion": True,
                "round": round_num,
            })


async def run_cross_talk():
    """Manual cross-talk triggered by the Discuss button."""
    active = get_active_participants()
    if len(active) < 2:
        await broadcast({"type": "message", "role": "assistant", "name": "System", "color": "#666",
                         "content": "Need at least 2 active participants for discussion."})
        return
    # REMOVED 2026-02-25 — deliberation_state["active"] = True
    await update_deliberation_state("active", True)  # ADDED 2026-02-25
    deliberation_state["paused"] = False
    deliberation_state["stop_requested"] = False
    await broadcast({"type": "round_separator", "round": "manual"})
    await run_discussion_round(active, round_num=1)
    await update_deliberation_state("active", False)
    await broadcast({"type": "deliberation_end"})


async def run_directed_discussion(mentioned: list[dict], topic: str, rounds: int = 2):
    """Run a focused discussion between specifically mentioned AIs."""
    names = [p["name"] for p in mentioned]
    name_list = ", ".join(names)

    # Add user message to history
    conversation_history.append({"role": "user", "name": "You", "content": topic})
    await broadcast({"type": "message", "role": "user", "name": "You", "content": topic})
    trim_conversation_history()
    await broadcast({"type": "directed_start", "participants": names, "topic": topic})

    directed_prompt = (
        "You are in a focused discussion with {others}. The human asked you specifically to discuss: {topic}\n"
        "Address {others} directly by name. Share your perspective, then react to what they say. "
        "Be direct, specific, and concise (1-3 paragraphs). This is a real conversation — "
        "challenge, agree, build on ideas, ask follow-up questions."
    )

    # REMOVED 2026-02-25 — deliberation_state["active"] = True
    await update_deliberation_state("active", True)  # ADDED 2026-02-25
    deliberation_state["paused"] = False
    deliberation_state["stop_requested"] = False

    stopped = False
    for round_num in range(1, rounds + 1):
        if stopped:
            break
        if round_num > 1:
            await broadcast({"type": "round_separator", "round": round_num})

        for participant in mentioned:
            status = await check_deliberation_control()
            if status == "stop":
                stopped = True
                break
            others = [n for n in names if n != participant["name"]]
            others_str = " and ".join(others)

            if participant.get("persona"):
                system_prompt = f"{participant['persona']}\n\n{directed_prompt.format(others=others_str, topic=topic)}"
            else:
                system_prompt = directed_prompt.format(others=others_str, topic=topic)

            messages = [{"role": "system", "content": system_prompt}]
            for msg in conversation_history[-16:]:
                if msg["role"] == "user":
                    messages.append({"role": "user", "content": msg["content"]})
                elif msg.get("name") == participant["name"]:
                    messages.append({"role": "assistant", "content": msg["content"]})
                else:
                    messages.append({"role": "user", "content": f"[{msg.get('name', 'AI')}]: {msg['content']}"})

            await broadcast({"type": "thinking", "name": participant["name"], "color": participant["color"]})
            response = await ask_model(participant["id"], participant["name"], messages)

            refs = detect_references(response, others)
            msg = {"role": "assistant", "name": participant["name"], "content": response}
            conversation_history.append(msg)
            await broadcast({
                "type": "message",
                "role": "assistant",
                "name": participant["name"],
                "color": participant["color"],
                "badge": participant["type"],
                "content": response,
                "references": refs,
                "is_discussion": True,
                "round": round_num,
            })

    await update_deliberation_state("active", False)
    if stopped:
        await broadcast({"type": "deliberation_stopped"})
    else:
        await broadcast({"type": "directed_end", "participants": names})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global max_deliberation_rounds
    await websocket.accept()
    connected_clients.append(websocket)

    # Send participant list, settings, and deliberation state
    await websocket.send_json({"type": "participants", "data": ALL_PARTICIPANTS})
    await websocket.send_json({"type": "settings", "max_rounds": max_deliberation_rounds})
    await websocket.send_json({"type": "deliberation_state", "data": deliberation_state})
    await websocket.send_json({"type": "presets", "data": PRESETS})

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
                asyncio.create_task(run_serialized_job(lambda: run_roundtable(data["content"]), websocket))
            elif data.get("type") == "crosstalk":
                asyncio.create_task(run_serialized_job(run_cross_talk, websocket))
            elif data.get("type") == "toggle":
                name = data.get("name")
                for p in ALL_PARTICIPANTS:
                    if p["name"] == name:
                        p["enabled"] = not p["enabled"]
                        break
                await broadcast({"type": "participants", "data": ALL_PARTICIPANTS})
            elif data.get("type") == "stop":
                deliberation_state["stop_requested"] = True
                deliberation_state["paused"] = False
            elif data.get("type") == "pause":
                if deliberation_state["active"]:
                    deliberation_state["paused"] = True
                    await broadcast({"type": "deliberation_paused"})
            elif data.get("type") == "resume":
                content = data.get("content", "").strip()
                if content:
                    conversation_history.append({"role": "user", "name": "You", "content": content})
                    await broadcast({"type": "message", "role": "user", "name": "You", "content": content})
                deliberation_state["paused"] = False
                await broadcast({"type": "deliberation_resumed"})
            elif data.get("type") == "activate_preset":
                preset_id = data.get("preset")
                preset = PRESETS.get(preset_id)
                if preset:
                    member_names = [m.lower() for m in preset["members"]]
                    for p in ALL_PARTICIPANTS:
                        p["enabled"] = p["name"].lower() in member_names
                    await broadcast({"type": "participants", "data": ALL_PARTICIPANTS})
            elif data.get("type") == "set_max_rounds":
                max_deliberation_rounds = max(0, min(10, int(data.get("rounds", 0))))
                await broadcast({"type": "settings", "max_rounds": max_deliberation_rounds})
            elif data.get("type") == "research_persona":
                asyncio.create_task(handle_research_persona(data, websocket))
            elif data.get("type") == "remove_persona":
                name = data.get("name", "")
                ALL_PARTICIPANTS[:] = [p for p in ALL_PARTICIPANTS if not (p["name"] == name and p.get("researched"))]
                save_personas()
                await broadcast({"type": "participants", "data": ALL_PARTICIPANTS})
            elif data.get("type") == "suggest_model":
                person = data.get("person", "")
                suggested = suggest_research_model(person)
                await websocket.send_json({"type": "model_suggestion", "person": person, "model": suggested})
            elif data.get("type") == "directed":
                participant_id = data.get("participant_id", "")
                message = data.get("message", "").strip()
                if message and participant_id:
                    target = next((p for p in ALL_PARTICIPANTS if p["name"] == participant_id or p["id"] == participant_id), None)
                    if target:
                        asyncio.create_task(run_serialized_job(
                            lambda: run_directed_discussion([target], message, rounds=1), websocket))
            elif data.get("type") == "dev_bar_message":
                asyncio.create_task(handle_dev_bar_message(data, websocket))
            elif data.get("type") == "dev_bar_apply":
                asyncio.create_task(handle_dev_bar_apply(data, websocket))
            elif data.get("type") == "dev_bar_clear":
                dev_bar_history.clear()
                await websocket.send_json({"type": "dev_bar_cleared"})
            # --- Phase 1: Task Board, Jobs, Projects, Decisions ---
            elif data.get("type") == "create_task":
                task = create_task_obj(
                    title=data.get("title", "Untitled"),
                    description=data.get("description", ""),
                    project=data.get("project") or ACTIVE_PROJECT.get("code") or "default",
                    priority=data.get("priority", "medium"),
                    team=data.get("team"),
                    assignee=data.get("assignee"),
                    language=data.get("language"),
                    depends_on=data.get("depends_on", []),
                    integration_notes=data.get("integration_notes"),
                )
                TASK_STORE[task["task_id"]] = task
                save_tasks()
                await broadcast({"type": "task_created", "task": task})
                if data.get("team"):
                    await assemble_team_for_task(task)
            elif data.get("type") == "update_task":
                tid = data.get("task_id", "")
                task = TASK_STORE.get(tid)
                if task:
                    if data.get("status"):
                        task["status"] = data["status"]
                    if data.get("assignee") is not None:
                        task["assignee"] = data["assignee"]
                    if data.get("result") is not None:
                        task["result"] = data["result"]
                    if data.get("integration_notes") is not None:
                        task["integration_notes"] = data["integration_notes"]
                    task["updated_at"] = datetime.now().isoformat()
                    if data.get("status") == "done":
                        recompute_blocked(tid)
                    save_tasks()
                    await broadcast({"type": "task_updated", "task": task})
            elif data.get("type") == "list_tasks":
                tasks = list(TASK_STORE.values())
                proj = data.get("project")
                if proj:
                    tasks = [t for t in tasks if t["project"] == proj]
                st = data.get("status")
                if st:
                    tasks = [t for t in tasks if t["status"] == st]
                tm = data.get("team")
                if tm:
                    tasks = [t for t in tasks if t.get("team") == tm]
                await websocket.send_json({"type": "tasks_list", "tasks": tasks, "project": proj})
            elif data.get("type") == "trigger_job":
                job_type = data.get("job_type", "strategy-session")
                project = data.get("project") or ACTIVE_PROJECT.get("code")
                params = data.get("params") or {}
                try:
                    client = get_http_client()
                    resp = await client.post(
                        f"{CREWAI_URL}/v1/agents/{job_type}",
                        json=params, timeout=30.0,
                    )
                    if resp.status_code == 200:
                        rdata = resp.json()
                        job_id = rdata.get("job_id", uuid.uuid4().hex[:8])
                        TRACKED_JOBS[job_id] = {
                            "job_id": job_id, "job_type": job_type,
                            "project": project, "status": rdata.get("status", "queued"),
                            "result": None, "triggered_at": datetime.now().isoformat(),
                        }
                        await broadcast({
                            "type": "job_started", "job_id": job_id, "job_type": job_type,
                            "description": f"{job_type} for {project or 'general'}", "project": project,
                        })
                    else:
                        await websocket.send_json({"type": "job_error", "job_id": "", "error": f"CrewAI HTTP {resp.status_code}"})
                except Exception as e:
                    await websocket.send_json({"type": "job_error", "job_id": "", "error": str(e)[:200]})
            elif data.get("type") == "approve_decision":
                did = data.get("decision_id", "")
                for d in DECISION_STORE:
                    if d["decision_id"] == did:
                        d["status"] = "approved"
                        d["approved_by"] = "user"
                        save_decisions()
                        await broadcast({"type": "decision_executing", "decision_id": did})
                        if d.get("action"):
                            try:
                                client = get_http_client()
                                resp = await client.post(f"{CREWAI_URL}/v1/agents/{d['action']}", json={}, timeout=30.0)
                                if resp.status_code == 200:
                                    rdata = resp.json()
                                    job_id = rdata.get("job_id", uuid.uuid4().hex[:8])
                                    TRACKED_JOBS[job_id] = {
                                        "job_id": job_id, "job_type": d["action"],
                                        "project": d.get("project"), "status": "queued",
                                        "result": None, "triggered_at": datetime.now().isoformat(),
                                    }
                                    d["status"] = "executed"
                                    d["outcome"] = f"Job {job_id} triggered"
                                    save_decisions()
                                    await broadcast({
                                        "type": "job_started", "job_id": job_id, "job_type": d["action"],
                                        "description": d["description"], "project": d.get("project"),
                                    })
                            except Exception:
                                pass
                        break
            elif data.get("type") == "reject_decision":
                did = data.get("decision_id", "")
                for d in DECISION_STORE:
                    if d["decision_id"] == did:
                        d["status"] = "rejected"
                        save_decisions()
                        await broadcast({"type": "decision_rejected", "decision_id": did})
                        break
            elif data.get("type") == "set_project":
                code = data.get("project", "")
                if code in PROJECT_STORE:
                    for p in PROJECT_STORE.values():
                        p["active"] = False
                    PROJECT_STORE[code]["active"] = True
                    ACTIVE_PROJECT["code"] = code
                    save_projects()
                    await websocket.send_json({"type": "system", "event": "project_changed", "data": {"project": code}})
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
    uptime_secs = int(time.time() - start_time)
    hours, remainder = divmod(uptime_secs, 3600)
    minutes, secs = divmod(remainder, 60)
    return {
        "status": "ok",
        "service": "collab-chat",
        "active": [p["name"] for p in active],
        "total": len(ALL_PARTICIPANTS),
        "uptime": f"{hours}h {minutes}m {secs}s",
        "uptime_seconds": uptime_secs,
        "model_stats": MODEL_STATS,
    }


@app.get("/api/model-stats")
async def model_stats():
    """Return per-model latency and error statistics."""
    return {"models": MODEL_STATS}


@app.get("/api/minutes")
async def get_minutes():
    """Export conversation as markdown meeting minutes."""

    active = get_active_participants()
    active_names = [p["name"] for p in active]
    all_names = list(dict.fromkeys(
        msg.get("name", "Unknown") for msg in conversation_history if msg.get("name") != "You"
    ))

    lines = []
    lines.append("# AI Roundtable — Meeting Minutes")
    lines.append(f"\n**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if all_names:
        lines.append(f"**Participants:** {', '.join(all_names)}")
    lines.append(f"**Currently active:** {', '.join(active_names) if active_names else 'None'}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for msg in conversation_history:
        name = msg.get("name", "Unknown")
        content = msg.get("content", "")
        role = msg.get("role", "")
        if role == "user":
            lines.append(f"## User")
            lines.append(f"\n{content}\n")
        else:
            lines.append(f"### {name}")
            lines.append(f"\n{content}\n")

    return {"markdown": "\n".join(lines)}


# Pending edits waiting for user approval
pending_edits: dict[str, dict] = {}

# Dev bar conversation history (separate from main chat)
dev_bar_history: list[dict] = []


class ApplyEditRequest(BaseModel):
    instruction: str
    sender: str = "Unknown"
    reason: str = ""


class ApproveEditRequest(BaseModel):
    editor_model: str = "claude-opus-4-6"
    reason: str = ""


@app.post("/api/propose-edit")
async def propose_edit(request: ApplyEditRequest):
    """Queue an AI response as a proposed edit. Returns an edit_id for approval."""
    edit_id = uuid.uuid4().hex[:8]
    pending_edits[edit_id] = {
        "instruction": request.instruction,
        "sender": request.sender,
        "reason": request.reason,
        "status": "pending",
        "result": None,
        "editor_model": None,
    }
    await broadcast({
        "type": "edit_proposed",
        "edit_id": edit_id,
        "sender": request.sender,
        "instruction": request.instruction[:200] + ("..." if len(request.instruction) > 200 else ""),
    })
    return {"edit_id": edit_id, "status": "pending"}


@app.post("/api/approve-edit/{edit_id}")
async def approve_edit(edit_id: str, request: Optional[ApproveEditRequest] = None):
    """Approve and execute a pending edit using the chosen AI model."""
    if request is None:
        request = ApproveEditRequest()

    edit = pending_edits.get(edit_id)
    if not edit:
        return {"error": "Edit not found"}
    if edit["status"] != "pending":
        return {"error": f"Edit already {edit['status']}"}

    editor_model = request.editor_model
    reason = request.reason or edit.get("reason", "")
    edit["status"] = "running"
    edit["editor_model"] = editor_model
    edit["reason"] = reason
    await broadcast({"type": "edit_running", "edit_id": edit_id, "editor": editor_model})

    instruction = edit["instruction"]
    source_dir = Path(__file__).parent
    try:
        backup_path = create_backup(f"edit_{edit_id}", reason)
    except Exception:
        backup_path = None

    # Read current source files to include in context
    try:
        main_py = (source_dir / "main.py").read_text()
        index_html = (source_dir / "index.html").read_text()
    except Exception as e:
        edit["status"] = "error"
        await broadcast({"type": "edit_failed", "edit_id": edit_id, "error": f"Cannot read source: {e}"})
        return {"error": f"Cannot read source: {e}"}

    today = datetime.now().strftime("%Y-%m-%d")

    # For Claude models, use claude-code container (can actually edit files)
    if editor_model.startswith("claude-"):
        prompt = (
            f"You are editing the AI Roundtable collab-chat application.\n"
            f"Source files are in /collab-chat/: main.py (FastAPI backend) and index.html (frontend).\n"
            f"Today is {today}.\n\n"
            f"{SAFE_EDIT_INSTRUCTIONS}\n\n"
            f"Apply this change:\n{instruction}\n\n"
            f"Reason for edit: {reason}\n\n"
            f"Make minimal, targeted edits following the SAFE EDIT rules above."
        )
        claude_code_url = CLAUDE_CODE_URL
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{claude_code_url}/v1/code/execute",
                    json={"prompt": prompt, "working_dir": "/collab-chat"},
                )
                if resp.status_code != 200:
                    raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
                result = resp.json().get("output", "No output")
        except Exception as e:
            error_msg = str(e)[:200]
            edit["status"] = "error"
            edit["result"] = error_msg
            await broadcast({"type": "edit_failed", "edit_id": edit_id, "error": error_msg})
            return {"edit_id": edit_id, "status": "error", "error": error_msg}
    else:
        # For Grok, DeepSeek, etc — use the router to get edit instructions,
        # then apply them via claude-code (since only Claude Code CLI can write files)
        plan_prompt = (
            f"You are editing the AI Roundtable collab-chat application. Below are the COMPLETE source files.\n\n"
            f"## main.py (FastAPI backend — COMPLETE FILE)\n```python\n{main_py}\n```\n\n"
            f"## index.html (Frontend — COMPLETE FILE)\n```html\n{index_html}\n```\n\n"
            f"## Requested change\n{instruction}\n\n"
            f"## Reason\n{reason}\n\n"
            f"Write the EXACT edits needed as a series of search-and-replace instructions.\n"
            f"Format each edit as:\n"
            f"FILE: <filename>\n"
            f"FIND:\n```\n<exact text to find>\n```\n"
            f"REPLACE:\n```\n<replacement text>\n```\n\n"
            f"Be precise — the FIND text must match the source EXACTLY (copy-paste from above). Make minimal, targeted changes. Do NOT ask for more code — the complete files are provided above."
        )
        try:
            # Get edit plan from chosen model via router
            plan_msgs = [{"role": "user", "content": plan_prompt}]
            edit_plan = await ask_model(editor_model, editor_model, plan_msgs)

            if edit_plan.startswith("[Error") or edit_plan.startswith("[Timeout"):
                raise Exception(edit_plan)

            # Execute the plan via claude-code
            apply_prompt = (
                f"You are editing the AI Roundtable collab-chat application.\n"
                f"Source files are in /collab-chat/: main.py and index.html.\n\n"
                f"Apply these edits exactly as specified by {editor_model}:\n\n{edit_plan}\n\n"
                f"Use the Edit tool to make each change. Do not deviate from the instructions above."
            )
            claude_code_url = CLAUDE_CODE_URL
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{claude_code_url}/v1/code/execute",
                    json={"prompt": apply_prompt, "working_dir": "/collab-chat"},
                )
                if resp.status_code != 200:
                    raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
                result = f"[{editor_model} planned, Claude applied]\n\n{resp.json().get('output', 'No output')}"
        except Exception as e:
            error_msg = str(e)[:200]
            edit["status"] = "error"
            edit["result"] = error_msg
            await broadcast({"type": "edit_failed", "edit_id": edit_id, "error": error_msg})
            return {"edit_id": edit_id, "status": "error", "error": error_msg}

    # Log the edit

    log_entry = (
        f"\n## Edit {edit_id} — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"**Editor:** {editor_model}\n"
        f"**Proposed by:** {edit['sender']}\n"
        f"**Reason:** {reason or 'No reason given'}\n"
        f"**Backup:** {backup_path.relative_to(source_dir) if backup_path else 'Backup failed'}\n"
        f"**Instruction:** {instruction[:300]}\n"
        f"**Result:** {result[:300]}\n"
        f"---\n"
    )
    log_path = source_dir / "edit_log.md"
    try:
        existing = log_path.read_text() if log_path.exists() else "# Collab Chat Edit Log\n"
        log_path.write_text(existing + log_entry)
    except Exception:
        pass  # Non-critical

    edit["status"] = "applied"
    edit["result"] = result
    await broadcast({
        "type": "edit_applied",
        "edit_id": edit_id,
        "editor": editor_model,
        "result": result[:500],
    })
    return {"edit_id": edit_id, "status": "applied", "editor": editor_model, "result": result[:500]}


@app.post("/api/reject-edit/{edit_id}")
async def reject_edit(edit_id: str):
    """Reject a pending edit."""
    edit = pending_edits.get(edit_id)
    if not edit:
        return {"error": "Edit not found"}
    edit["status"] = "rejected"
    await broadcast({"type": "edit_rejected", "edit_id": edit_id})
    return {"edit_id": edit_id, "status": "rejected"}


@app.get("/api/pending-edits")
async def list_pending_edits():
    """List all pending edits."""
    return {eid: {"sender": e["sender"], "status": e["status"], "instruction": e["instruction"][:200]}
            for eid, e in pending_edits.items()}


@app.post("/api/clear")
async def clear_history():
    """Clear conversation history."""
    conversation_history.clear()
    await broadcast({"type": "clear"})
    return {"status": "cleared"}


# ============ Participant & Preset Management ============

@app.get("/api/participants")
async def list_participants():
    """Return all participants with enabled status."""
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "color": p["color"],
            "type": p["type"],
            "enabled": p.get("enabled", False),
            "persona": p.get("persona"),
            "researched": p.get("researched", False),
        }
        for p in ALL_PARTICIPANTS
    ]


class ParticipantUpdate(BaseModel):
    enabled: Optional[bool] = None
    persona: Optional[str] = None


@app.put("/api/participants/{name}")
async def update_participant(name: str, update: ParticipantUpdate):
    """Toggle enable/disable or update persona for a participant."""
    participant = next((p for p in ALL_PARTICIPANTS if p["name"] == name), None)
    if not participant:
        return JSONResponse(status_code=404, content={"error": f"Participant '{name}' not found"})
    if update.enabled is not None:
        participant["enabled"] = update.enabled
    if update.persona is not None:
        participant["persona"] = update.persona
        if participant["type"] == "model" and update.persona:
            participant["type"] = "agent"
    await broadcast({"type": "participants", "data": ALL_PARTICIPANTS})
    return {"status": "updated", "participant": participant["name"], "enabled": participant["enabled"]}


PRESETS_FILE = Path(__file__).with_name("presets.json")


def load_presets_file() -> dict[str, Any]:
    """Load presets from presets.json, falling back to in-memory PRESETS."""
    if PRESETS_FILE.exists():
        try:
            data = json.loads(PRESETS_FILE.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


@app.get("/api/presets")
async def list_presets():
    """Return available roundtable presets (in-memory + file-based)."""
    file_presets = load_presets_file()
    merged = {**PRESETS, **file_presets}
    return merged


# ============ Structured Roundtable Sessions ============

# Active structured session state
structured_session: dict[str, Any] = {
    "active": False,
    "preset": None,
    "round": 0,
    "total_rounds": 0,
    "phase": "idle",  # idle | running | voting | synthesis | complete
    "votes": {},  # round_num -> {participant_name: vote_text}
    "positions": {},  # participant_name -> latest position summary
}


class RoundtableStartRequest(BaseModel):
    preset: Optional[str] = None
    topic: Optional[str] = None
    rounds: Optional[int] = None


@app.post("/api/roundtable/start")
async def start_roundtable(req: RoundtableStartRequest):
    """Start a structured roundtable session with optional preset."""
    if deliberation_state["active"]:
        return JSONResponse(status_code=409, content={"error": "A session is already running"})

    # Apply preset if specified
    preset_data = None
    if req.preset:
        all_presets = {**PRESETS, **load_presets_file()}
        preset_data = all_presets.get(req.preset)
        if not preset_data:
            return JSONResponse(status_code=404, content={"error": f"Preset '{req.preset}' not found"})
        member_names = [m.lower() for m in preset_data["members"]]
        for p in ALL_PARTICIPANTS:
            p["enabled"] = p["name"].lower() in member_names
        await broadcast({"type": "participants", "data": ALL_PARTICIPANTS})

    total_rounds = req.rounds or (preset_data or {}).get("deliberation_rounds", 2)
    structured_session.update({
        "active": True,
        "preset": req.preset,
        "round": 0,
        "total_rounds": total_rounds,
        "phase": "running",
        "votes": {},
        "positions": {},
    })

    await broadcast({"type": "status", "message": "Structured session started",
                     "phase": "round_start", "round": 1, "metadata": {"preset": req.preset, "total_rounds": total_rounds}})

    # If topic provided, kick off the roundtable
    if req.topic:
        asyncio.create_task(run_serialized_job(lambda: run_roundtable(req.topic), None))

    return {"status": "started", "preset": req.preset, "total_rounds": total_rounds,
            "active_participants": [p["name"] for p in get_active_participants()]}


@app.get("/api/roundtable/status")
async def roundtable_status():
    """Return current structured session state."""
    return {
        "deliberation": deliberation_state,
        "session": {
            "active": structured_session["active"],
            "preset": structured_session["preset"],
            "round": structured_session["round"],
            "total_rounds": structured_session["total_rounds"],
            "phase": structured_session["phase"],
            "vote_count": {str(k): len(v) for k, v in structured_session["votes"].items()},
        },
        "active_participants": [p["name"] for p in get_active_participants()],
        "total_participants": len(ALL_PARTICIPANTS),
    }


class VoteRequest(BaseModel):
    participant: str
    vote: str  # "agree", "disagree", "abstain", or free text position


@app.post("/api/roundtable/vote")
async def submit_vote(req: VoteRequest):
    """Accept a participant vote for the current round."""
    if not structured_session["active"]:
        return JSONResponse(status_code=400, content={"error": "No active session"})

    round_key = structured_session["round"] or 1
    if round_key not in structured_session["votes"]:
        structured_session["votes"][round_key] = {}
    structured_session["votes"][round_key][req.participant] = req.vote
    structured_session["positions"][req.participant] = req.vote

    await broadcast({"type": "status", "message": f"{req.participant} voted: {req.vote}",
                     "phase": "round_end", "round": round_key,
                     "metadata": {"voter": req.participant, "vote": req.vote}})

    return {"status": "recorded", "round": round_key, "participant": req.participant}


# ============ Export ============

@app.get("/api/export/{fmt}")
async def export_conversation(fmt: str):
    """Export conversation as JSON, Markdown, or CSV."""
    if fmt == "json":
        return JSONResponse(content={"messages": conversation_history, "exported_at": datetime.now().isoformat()})
    elif fmt == "markdown" or fmt == "md":
        lines = [f"# AI Roundtable — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
        for msg in conversation_history:
            name = msg.get("name", msg["role"].title())
            lines.append(f"**{name}:** {msg['content']}\n")
        return HTMLResponse(content="\n".join(lines), media_type="text/markdown")
    elif fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["role", "name", "content"])
        for msg in conversation_history:
            writer.writerow([msg["role"], msg.get("name", ""), msg["content"]])
        return HTMLResponse(content=buf.getvalue(), media_type="text/csv")
    else:
        return JSONResponse(status_code=400, content={"error": f"Unsupported format: {fmt}. Use json, markdown, or csv."})


# ============ Task Board ============

class TaskCreateRequest(BaseModel):
    title: str
    description: str = ""
    project: Optional[str] = None
    team: Optional[str] = None
    assignee: Optional[str] = None
    priority: str = "medium"
    language: Optional[str] = None
    depends_on: list[str] = []
    integration_notes: Optional[str] = None


class TaskUpdateRequest(BaseModel):
    status: Optional[str] = None
    assignee: Optional[str] = None
    result: Optional[str] = None
    integration_notes: Optional[str] = None
    team: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None


@app.post("/api/tasks")
async def create_task(req: TaskCreateRequest):
    """Create a new task."""
    project = req.project or ACTIVE_PROJECT.get("code") or "default"
    task = create_task_obj(
        title=req.title,
        description=req.description,
        project=project,
        priority=req.priority,
        team=req.team,
        assignee=req.assignee,
        language=req.language,
        depends_on=req.depends_on,
        integration_notes=req.integration_notes,
    )
    TASK_STORE[task["task_id"]] = task
    save_tasks()
    await broadcast({"type": "task_created", "task": task})

    # If team specified, assemble team
    if req.team:
        await assemble_team_for_task(task)

    return task


@app.get("/api/tasks")
async def list_tasks(
    project: Optional[str] = None,
    status: Optional[str] = None,
    team: Optional[str] = None,
    assignee: Optional[str] = None,
):
    """List tasks with optional filters."""
    tasks = list(TASK_STORE.values())
    if project:
        tasks = [t for t in tasks if t["project"] == project]
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    if team:
        tasks = [t for t in tasks if t.get("team") == team]
    if assignee:
        tasks = [t for t in tasks if t.get("assignee") == assignee]
    tasks.sort(key=lambda t: (
        {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(t["priority"], 2),
        t["created_at"],
    ))
    return {"tasks": tasks, "total": len(tasks)}


@app.get("/api/tasks/board")
async def task_board(project: Optional[str] = None):
    """Get tasks grouped by status (kanban view)."""
    tasks = list(TASK_STORE.values())
    if project:
        tasks = [t for t in tasks if t["project"] == project]
    board = {}
    for status in ["backlog", "assigned", "in_progress", "review", "done", "blocked"]:
        board[status] = [t for t in tasks if t["status"] == status]
    return {"board": board, "project": project}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a single task."""
    task = TASK_STORE.get(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})
    return task


@app.put("/api/tasks/{task_id}")
async def update_task(task_id: str, req: TaskUpdateRequest):
    """Update a task."""
    task = TASK_STORE.get(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})

    if req.status is not None:
        task["status"] = req.status
    if req.assignee is not None:
        task["assignee"] = req.assignee
    if req.result is not None:
        task["result"] = req.result
    if req.integration_notes is not None:
        task["integration_notes"] = req.integration_notes
    if req.team is not None:
        task["team"] = req.team
    if req.title is not None:
        task["title"] = req.title
    if req.description is not None:
        task["description"] = req.description
    task["updated_at"] = datetime.now().isoformat()

    # If task completed, unblock dependents
    if req.status == "done":
        recompute_blocked(task_id)

    save_tasks()
    await broadcast({"type": "task_updated", "task": task})
    return task


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task."""
    if task_id not in TASK_STORE:
        return JSONResponse(status_code=404, content={"error": "Task not found"})
    del TASK_STORE[task_id]
    save_tasks()
    return {"status": "deleted", "task_id": task_id}


@app.post("/api/tasks/{task_id}/discuss")
async def discuss_task(task_id: str):
    """Start a roundtable discussion about a specific task."""
    task = TASK_STORE.get(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})

    # Assemble team if specified
    if task.get("team"):
        await assemble_team_for_task(task)

    # Build discussion prompt from task details
    prompt_parts = [f"TASK: {task['title']}"]
    if task.get("description"):
        prompt_parts.append(f"Description: {task['description']}")
    if task.get("language"):
        prompt_parts.append(f"Language: {task['language']}")
    if task.get("integration_notes"):
        prompt_parts.append(f"Integration notes: {task['integration_notes']}")
    if task.get("depends_on"):
        dep_titles = [TASK_STORE.get(d, {}).get("title", d) for d in task["depends_on"]]
        prompt_parts.append(f"Depends on: {', '.join(dep_titles)}")

    prompt = "\n".join(prompt_parts)
    prompt += "\n\nDiscuss this task. Provide your expert perspective, identify risks, propose implementation details, and coordinate with the team."

    # Update task status
    if task["status"] in ("backlog", "assigned"):
        task["status"] = "in_progress"
        task["updated_at"] = datetime.now().isoformat()
        save_tasks()
        await broadcast({"type": "task_updated", "task": task})

    # Kick off roundtable
    asyncio.create_task(run_serialized_job(lambda: run_roundtable(prompt), None))

    return {"status": "discussion_started", "task_id": task_id, "team": task.get("team")}


async def assemble_team_for_task(task: dict[str, Any]):
    """Activate participants for a task's team preset."""
    team_name = task.get("team")
    if not team_name:
        return

    # Check PRESETS (in-memory) and presets.json
    all_presets = {**PRESETS, **load_presets_file()}
    preset = all_presets.get(team_name)
    if not preset:
        return

    members = preset.get("members", preset.get("participants", []))
    member_names = [m.lower() for m in members]
    activated = []
    for p in ALL_PARTICIPANTS:
        if p["name"].lower() in member_names:
            p["enabled"] = True
            activated.append(p["name"])

    if activated:
        await broadcast({"type": "participants", "data": ALL_PARTICIPANTS})
        await broadcast({
            "type": "team_assembled",
            "project": task.get("project", ""),
            "team": team_name,
            "members": activated,
        })


# ============ Project Management ============

class ProjectCreateRequest(BaseModel):
    code: str
    name: str
    description: str = ""
    repo_path: Optional[str] = None
    tech_stack: list[str] = []
    teams: list[str] = []


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    repo_path: Optional[str] = None
    tech_stack: Optional[list[str]] = None
    teams: Optional[list[str]] = None
    active: Optional[bool] = None


@app.get("/api/projects")
async def list_projects():
    """List all registered projects."""
    projects = []
    for proj in PROJECT_STORE.values():
        task_counts = {}
        for s in ["backlog", "assigned", "in_progress", "review", "done", "blocked"]:
            task_counts[s] = sum(1 for t in TASK_STORE.values()
                                 if t["project"] == proj["code"] and t["status"] == s)
        projects.append({**proj, "task_counts": task_counts})
    return {"projects": projects}


@app.get("/api/projects/{code}")
async def get_project(code: str):
    """Get project details with task summary."""
    proj = PROJECT_STORE.get(code)
    if not proj:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    task_counts = {}
    for s in ["backlog", "assigned", "in_progress", "review", "done", "blocked"]:
        task_counts[s] = sum(1 for t in TASK_STORE.values()
                              if t["project"] == code and t["status"] == s)
    tasks = [t for t in TASK_STORE.values() if t["project"] == code]
    return {**proj, "task_counts": task_counts, "tasks": tasks}


@app.post("/api/projects")
async def create_project(req: ProjectCreateRequest):
    """Register a new project."""
    if req.code in PROJECT_STORE:
        return JSONResponse(status_code=409, content={"error": "Project already exists"})
    proj = {
        "code": req.code,
        "name": req.name,
        "description": req.description,
        "repo_path": req.repo_path,
        "tech_stack": req.tech_stack,
        "teams": req.teams,
        "active": len(PROJECT_STORE) == 0,
        "created_at": datetime.now().isoformat(),
    }
    PROJECT_STORE[req.code] = proj
    if proj["active"]:
        ACTIVE_PROJECT["code"] = req.code
    save_projects()
    return proj


@app.put("/api/projects/{code}")
async def update_project(code: str, req: ProjectUpdateRequest):
    """Update project config."""
    proj = PROJECT_STORE.get(code)
    if not proj:
        return JSONResponse(status_code=404, content={"error": "Project not found"})
    if req.name is not None:
        proj["name"] = req.name
    if req.description is not None:
        proj["description"] = req.description
    if req.repo_path is not None:
        proj["repo_path"] = req.repo_path
    if req.tech_stack is not None:
        proj["tech_stack"] = req.tech_stack
    if req.teams is not None:
        proj["teams"] = req.teams
    if req.active is not None:
        if req.active:
            for p in PROJECT_STORE.values():
                p["active"] = False
            proj["active"] = True
            ACTIVE_PROJECT["code"] = code
        else:
            proj["active"] = False
            if ACTIVE_PROJECT["code"] == code:
                ACTIVE_PROJECT["code"] = None
    save_projects()
    return proj


# ============ CrewAI Job Integration ============

class JobTriggerRequest(BaseModel):
    job_type: str = "strategy-session"
    project: Optional[str] = None
    params: Optional[dict] = None


@app.post("/api/jobs/trigger")
async def trigger_job(req: JobTriggerRequest):
    """Trigger a CrewAI agent job."""
    project = req.project or ACTIVE_PROJECT.get("code")
    try:
        client = get_http_client()
        body = req.params or {}
        resp = await client.post(
            f"{CREWAI_URL}/v1/agents/{req.job_type}",
            json=body,
            timeout=30.0,
        )
        if resp.status_code != 200:
            return JSONResponse(status_code=resp.status_code,
                                content={"error": f"CrewAI returned {resp.status_code}: {resp.text[:200]}"})
        data = resp.json()
        job_id = data.get("job_id", uuid.uuid4().hex[:8])

        tracked = {
            "job_id": job_id,
            "job_type": req.job_type,
            "project": project,
            "status": data.get("status", "queued"),
            "result": None,
            "triggered_at": datetime.now().isoformat(),
        }
        TRACKED_JOBS[job_id] = tracked

        await broadcast({
            "type": "job_started",
            "job_id": job_id,
            "job_type": req.job_type,
            "description": f"{req.job_type} for {project or 'general'}",
            "project": project,
        })
        return tracked
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)[:300]})


@app.get("/api/jobs")
async def list_jobs(project: Optional[str] = None, status: Optional[str] = None):
    """List tracked jobs, also fetching from CrewAI."""
    try:
        client = get_http_client()
        resp = await client.get(f"{CREWAI_URL}/v1/agents/jobs", timeout=10.0)
        if resp.status_code == 200:
            crewai_jobs = resp.json()
            if isinstance(crewai_jobs, list):
                for j in crewai_jobs:
                    jid = j.get("job_id", "")
                    if jid and jid in TRACKED_JOBS:
                        TRACKED_JOBS[jid]["status"] = j.get("status", TRACKED_JOBS[jid]["status"])
                        if j.get("result"):
                            TRACKED_JOBS[jid]["result"] = j["result"]
    except Exception:
        pass

    jobs = list(TRACKED_JOBS.values())
    if project:
        jobs = [j for j in jobs if j.get("project") == project]
    if status:
        jobs = [j for j in jobs if j.get("status") == status]
    jobs.sort(key=lambda j: j.get("triggered_at", ""), reverse=True)
    return {"jobs": jobs, "total": len(jobs)}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job status, fetching fresh data from CrewAI."""
    try:
        client = get_http_client()
        resp = await client.get(f"{CREWAI_URL}/v1/agents/jobs/{job_id}", timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            if job_id in TRACKED_JOBS:
                TRACKED_JOBS[job_id]["status"] = data.get("status", TRACKED_JOBS[job_id]["status"])
                if data.get("result"):
                    TRACKED_JOBS[job_id]["result"] = data["result"]
                return TRACKED_JOBS[job_id]
            return data
    except Exception:
        pass

    if job_id in TRACKED_JOBS:
        return TRACKED_JOBS[job_id]
    return JSONResponse(status_code=404, content={"error": "Job not found"})


# ============ Decision Tracking ============

class DecisionCreateRequest(BaseModel):
    description: str
    project: Optional[str] = None
    action: Optional[str] = None
    decided_by: list[str] = []


@app.get("/api/decisions")
async def list_decisions(project: Optional[str] = None, limit: int = 50):
    """List recent decisions."""
    decisions = DECISION_STORE
    if project:
        decisions = [d for d in decisions if d.get("project") == project]
    return {"decisions": decisions[-limit:], "total": len(decisions)}


@app.post("/api/decisions")
async def create_decision(req: DecisionCreateRequest):
    """Record a decision."""
    decision = {
        "decision_id": uuid.uuid4().hex[:8],
        "project": req.project or ACTIVE_PROJECT.get("code"),
        "description": req.description,
        "action": req.action,
        "outcome": None,
        "decided_by": req.decided_by,
        "approved_by": None,
        "created_at": datetime.now().isoformat(),
        "status": "proposed",
    }
    DECISION_STORE.append(decision)
    save_decisions()
    await broadcast({
        "type": "decision_detected",
        "decision_id": decision["decision_id"],
        "action": decision["action"] or "",
        "description": decision["description"],
        "project": decision["project"],
    })
    return decision


# ============ Dashboard ============

@app.get("/api/dashboard")
async def get_dashboard(project: Optional[str] = None):
    """Combined dashboard: tasks, jobs, decisions."""
    proj_code = project or ACTIVE_PROJECT.get("code")

    tasks = list(TASK_STORE.values())
    if proj_code:
        tasks = [t for t in tasks if t["project"] == proj_code]
    task_counts = {}
    for s in ["backlog", "assigned", "in_progress", "review", "done", "blocked"]:
        task_counts[s] = sum(1 for t in tasks if t["status"] == s)

    active_jobs = [j for j in TRACKED_JOBS.values()
                   if j.get("status") in ("queued", "running")]
    if proj_code:
        active_jobs = [j for j in active_jobs if j.get("project") == proj_code]

    decisions = DECISION_STORE[-10:]
    if proj_code:
        decisions = [d for d in DECISION_STORE if d.get("project") == proj_code][-10:]

    pnl = {"revenue": 0, "expenses": 0, "profit": 0, "note": "P&L integration coming in Phase 2"}

    return {
        "project": proj_code,
        "project_name": PROJECT_STORE.get(proj_code, {}).get("name", proj_code) if proj_code else None,
        "task_counts": task_counts,
        "total_tasks": len(tasks),
        "active_jobs": len(active_jobs),
        "jobs": active_jobs,
        "recent_decisions": decisions,
        "pnl": pnl,
        "active_participants": [p["name"] for p in get_active_participants()],
    }


@app.get("/api/pnl")
async def get_pnl():
    """P&L summary. Phase 1 stub — Phase 2 will query PostgreSQL budget_ledger."""
    return {
        "revenue": 0,
        "expenses": 0,
        "profit": 0,
        "entries": [],
        "note": "P&L integration coming in Phase 2 — will query ai_mesh.budget_ledger",
    }


# ============ Job Poller (background) ============

async def poll_tracked_jobs():
    """Background task: poll CrewAI for job status updates every 15s."""
    while True:
        await asyncio.sleep(15)
        if not TRACKED_JOBS:
            continue
        active = {jid: j for jid, j in TRACKED_JOBS.items() if j.get("status") in ("queued", "running")}
        if not active:
            continue
        for job_id, job in active.items():
            try:
                client = get_http_client()
                resp = await client.get(f"{CREWAI_URL}/v1/agents/jobs/{job_id}", timeout=10.0)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                new_status = data.get("status", job["status"])
                if new_status != job["status"]:
                    job["status"] = new_status
                    if data.get("result"):
                        job["result"] = data["result"]
                    await broadcast({
                        "type": "job_update",
                        "job_id": job_id,
                        "status": new_status,
                        "result": (data.get("result") or "")[:500] if data.get("result") else None,
                        "progress": None,
                    })
                    # If job linked to a task, update the task
                    for t in TASK_STORE.values():
                        if t.get("job_id") == job_id:
                            if new_status == "completed":
                                t["status"] = "review"
                                t["result"] = (data.get("result") or "")[:1000]
                                t["updated_at"] = datetime.now().isoformat()
                                recompute_blocked(t["task_id"])
                                save_tasks()
                                await broadcast({"type": "task_updated", "task": t})
                            elif new_status == "failed":
                                t["status"] = "blocked"
                                t["updated_at"] = datetime.now().isoformat()
                                save_tasks()
                                await broadcast({"type": "task_updated", "task": t})
                            break
            except Exception:
                continue


# ============ Persona Research ============

PERSONA_RESEARCH_PROMPT = """You are creating a hyper-accurate AI persona of {person_name}.

Research this person deeply and create the most authentic representation possible. This persona will participate in business strategy discussions.

You must capture:

1. **Communication style**: How do they actually talk? What phrases do they repeat? Are they blunt, inspirational, analytical, provocative? Do they use metaphors, stories, data, or gut instinct? Give SPECIFIC examples of their speech patterns.

2. **Decision-making framework**: What principles drive their decisions? What do they optimize for? What would they NEVER do? What biases do they have? How do they evaluate risk?

3. **Core beliefs & philosophy**: What are their non-negotiable beliefs about business, life, and success? What books/thinkers influenced them? What's their mental model of the world?

4. **Domain expertise**: What specific areas do they know deeply? What industries, technologies, or strategies are they experts in? What unique insights do they bring?

5. **Controversial/bold takes**: What strong opinions do they hold that others disagree with? What makes them different from generic business advice?

6. **Known quotes & catchphrases**: Include real quotes they're famous for. These should appear naturally in the persona's responses.

7. **Weaknesses & blind spots**: What are they wrong about? What do they overlook? An accurate persona includes flaws.

8. **How they'd respond in a meeting**: If someone pitched them a SaaS idea, what would they focus on? What questions would they ask? What would excite them vs bore them?

Output format — write ONLY the persona text (no headers, no explanation). Start with "You are {person_name} — " and write in second person. The persona should be 300-500 words. Be specific, not generic. Include real quotes, real anecdotes, real decision patterns. This should sound like {person_name}, not a generic AI summary of them.

DO NOT water it down. Be bold, specific, and authentic. If they're controversial, be controversial. If they're blunt, be blunt. Accuracy over safety."""


async def handle_research_persona(data: dict, websocket: WebSocket):
    """Research a real person and add them as a roundtable participant."""
    person_name = data.get("person", "").strip()
    model_id = data.get("model", "").strip()
    if not person_name:
        return

    # If no model specified, suggest one
    if not model_id:
        model_id = suggest_research_model(person_name)

    # Check if persona already exists
    existing = next((p for p in ALL_PARTICIPANTS if p["name"].lower() == person_name.lower()), None)
    if existing:
        await websocket.send_json({
            "type": "persona_error",
            "error": f"{person_name} is already in the roundtable",
        })
        return

    model_info = next((p for p in ALL_PARTICIPANTS if p["id"] == model_id), None)
    model_name = model_info["name"] if model_info else model_id

    # Notify user that research is starting
    await broadcast({
        "type": "persona_researching",
        "person": person_name,
        "model": model_name,
    })

    # Do the research
    prompt = PERSONA_RESEARCH_PROMPT.format(person_name=person_name)
    messages = [{"role": "user", "content": prompt}]
    persona_text = await ask_model(model_id, model_name, messages)

    if persona_text.startswith("[Error") or persona_text.startswith("[Timeout"):
        await broadcast({
            "type": "persona_error",
            "person": person_name,
            "error": persona_text,
        })
        return

    # Create the participant entry
    color = next_persona_color()
    new_participant = {
        "id": model_id,
        "name": person_name,
        "color": color,
        "type": "agent",
        "persona": persona_text,
        "enabled": True,
        "researched": True,  # Flag to distinguish from built-in agents
    }
    ALL_PARTICIPANTS.append(new_participant)
    save_personas()

    # Broadcast updated participant list and success
    await broadcast({"type": "participants", "data": ALL_PARTICIPANTS})
    await broadcast({
        "type": "persona_added",
        "person": person_name,
        "model": model_name,
        "color": color,
        "persona_preview": persona_text[:300] + "..." if len(persona_text) > 300 else persona_text,
    })


# ============ Developer Bar ============

SAFE_EDIT_INSTRUCTIONS = """
CRITICAL EDITING RULES — you MUST follow these:

1. NEVER delete any line of code. Instead, COMMENT OUT removed lines with a date stamp.
   - For Python (.py): prefix with # REMOVED {date} —
   - For HTML (.html): wrap with <!-- REMOVED {date} — --> ... <!-- /REMOVED -->

2. NEW lines you add should have a comment marking when they were added:
   - For Python: # ADDED {date}
   - For HTML: <!-- ADDED {date} -->

3. The date format is YYYY-MM-DD (e.g., 2026-02-25).

4. This makes it easy to find and revert changes by searching for the date.

Example Python edit — replacing a line:
BEFORE:
    result = old_function(x)
AFTER:
    # REMOVED 2026-02-25 — result = old_function(x)
    result = new_function(x)  # ADDED 2026-02-25

Example HTML edit — replacing a section:
BEFORE:
    <button class="old">Click</button>
AFTER:
    <!-- REMOVED 2026-02-25 — <button class="old">Click</button> -->
    <button class="new">Click</button> <!-- ADDED 2026-02-25 -->
"""


async def handle_dev_bar_message(data: dict, websocket: WebSocket):
    """Handle a direct message from the dev bar to a specific AI model."""
    model_id = data.get("model", "claude-opus-4-6")
    content = data.get("content", "").strip()
    if not content:
        return

    # Find model info
    model_info = next((p for p in ALL_PARTICIPANTS if p["id"] == model_id), None)
    model_name = model_info["name"] if model_info else model_id

    # Add user message to dev bar history
    dev_bar_history.append({"role": "user", "content": content})

    # Send thinking indicator
    await websocket.send_json({"type": "dev_bar_thinking", "model": model_name})

    # Read current source files for context
    source_dir = Path(__file__).parent
    try:
        main_py = (source_dir / "main.py").read_text()
        index_html = (source_dir / "index.html").read_text()
    except Exception:
        main_py = "[Could not read main.py]"
        index_html = "[Could not read index.html]"

    # Build messages with full source context
    today = datetime.now().strftime("%Y-%m-%d")
    system_msg = (
        f"You are a developer assistant working on the AI Roundtable collab-chat application.\n"
        f"Today is {today}.\n\n"
        f"## Architecture context\n"
        f"- LAN-only personal tool (single user, 1-3 browser tabs), NOT a production SaaS app\n"
        f"- WebSocket-based multi-AI deliberation: participants are AI models/agents, not human users\n"
        f"- Self-modifying: the 'Apply as edit' feature lets AI propose code changes to THIS app — this is intentional, not a security hole\n"
        f"- Edits go through an explicit approve/reject UI flow, constrained by SAFE_EDIT_INSTRUCTIONS (comment-out-and-replace pattern)\n"
        f"- Runs in Docker on a home server (192.168.50.23), behind no public ingress\n"
        f"- connected_clients list is typically 1-3 entries; broadcast() does not need concurrent sends\n"
        f"- thinkingEls (frontend) tracks AI participant thinking animations, NOT user connections\n\n"
        f"The app has two source files:\n"
        f"- main.py (FastAPI backend with WebSocket)\n"
        f"- index.html (frontend with JS)\n\n"
        f"## main.py (COMPLETE)\n```python\n{main_py}\n```\n\n"
        f"## index.html (COMPLETE)\n```html\n{index_html}\n```\n\n"
        f"When suggesting code changes, be specific with search-and-replace format.\n"
        f"When analyzing code, consider the actual deployment context above — do not apply generic production-app checklists.\n"
        f"Always answer the developer's question directly."
    )

    messages = [{"role": "system", "content": system_msg}]
    # Include last 10 dev bar messages for context
    for msg in dev_bar_history[-10:]:
        messages.append(msg)

    response = await ask_model(model_id, model_name, messages)
    dev_bar_history.append({"role": "assistant", "name": model_name, "model": model_id, "content": response})

    await websocket.send_json({
        "type": "dev_bar_response",
        "model": model_name,
        "model_id": model_id,
        "content": response,
        "color": model_info["color"] if model_info else "#8b949e",
    })


async def handle_dev_bar_apply(data: dict, websocket: WebSocket):
    """Apply an edit from the dev bar using safe comment-out approach."""
    instruction = data.get("instruction", "").strip()
    model_id = data.get("model", "claude-opus-4-6")
    reason = data.get("reason", "Dev bar edit")

    if not instruction:
        await websocket.send_json({"type": "dev_bar_edit_failed", "error": "No instruction provided"})
        return

    model_info = next((p for p in ALL_PARTICIPANTS if p["id"] == model_id), None)
    model_name = model_info["name"] if model_info else model_id

    await websocket.send_json({"type": "dev_bar_edit_running", "model": model_name})

    source_dir = Path(__file__).parent
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        backup_label = f"devbar_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_path = create_backup(backup_label, reason)
    except Exception:
        backup_path = None

    # Read current source files
    try:
        main_py = (source_dir / "main.py").read_text()
        index_html = (source_dir / "index.html").read_text()
    except Exception as e:
        await websocket.send_json({"type": "dev_bar_edit_failed", "error": f"Cannot read source: {e}"})
        return

    # For Claude models, use claude-code with safe edit instructions
    claude_code_url = CLAUDE_CODE_URL

    if model_id.startswith("claude-"):
        prompt = (
            f"You are editing the AI Roundtable collab-chat application.\n"
            f"Source files are in /collab-chat/: main.py (FastAPI backend) and index.html (frontend).\n"
            f"Today is {today}.\n\n"
            f"{SAFE_EDIT_INSTRUCTIONS}\n\n"
            f"Apply this change:\n{instruction}\n\n"
            f"Reason: {reason}\n\n"
            f"Make minimal, targeted edits following the SAFE EDIT rules above."
        )
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{claude_code_url}/v1/code/execute",
                    json={"prompt": prompt, "working_dir": "/collab-chat"},
                )
                if resp.status_code != 200:
                    raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
                result = resp.json().get("output", "No output")
        except Exception as e:
            await websocket.send_json({"type": "dev_bar_edit_failed", "error": str(e)[:300]})
            return
    else:
        # Non-Claude: model plans, claude-code executes
        plan_prompt = (
            f"You are editing the AI Roundtable collab-chat application.\n"
            f"Today is {today}.\n\n"
            f"## main.py (COMPLETE)\n```python\n{main_py}\n```\n\n"
            f"## index.html (COMPLETE)\n```html\n{index_html}\n```\n\n"
            f"{SAFE_EDIT_INSTRUCTIONS}\n\n"
            f"## Requested change\n{instruction}\n\n"
            f"## Reason\n{reason}\n\n"
            f"Write the EXACT edits needed as search-and-replace instructions following the SAFE EDIT rules.\n"
            f"Format each edit as:\n"
            f"FILE: <filename>\n"
            f"FIND:\n```\n<exact text to find>\n```\n"
            f"REPLACE:\n```\n<replacement text with REMOVED/ADDED date comments>\n```\n\n"
            f"Be precise — the FIND text must match EXACTLY. Do NOT ask for more code."
        )
        try:
            plan_msgs = [{"role": "user", "content": plan_prompt}]
            edit_plan = await ask_model(model_id, model_name, plan_msgs)

            if edit_plan.startswith("[Error") or edit_plan.startswith("[Timeout"):
                raise Exception(edit_plan)

            apply_prompt = (
                f"You are editing the AI Roundtable collab-chat application.\n"
                f"Source files are in /collab-chat/: main.py and index.html.\n"
                f"Today is {today}.\n\n"
                f"{SAFE_EDIT_INSTRUCTIONS}\n\n"
                f"Apply these edits exactly as specified by {model_name}:\n\n{edit_plan}\n\n"
                f"Use the Edit tool to make each change. Follow the SAFE EDIT rules."
            )
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{claude_code_url}/v1/code/execute",
                    json={"prompt": apply_prompt, "working_dir": "/collab-chat"},
                )
                if resp.status_code != 200:
                    raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
                result = f"[{model_name} planned, Claude applied]\n\n{resp.json().get('output', 'No output')}"
        except Exception as e:
            await websocket.send_json({"type": "dev_bar_edit_failed", "error": str(e)[:300]})
            return

    # Log the edit
    log_entry = (
        f"\n## Dev Bar Edit — {today} {datetime.now().strftime('%H:%M')}\n"
        f"**Editor:** {model_id}\n"
        f"**Reason:** {reason}\n"
        f"**Backup:** {backup_path.relative_to(source_dir) if backup_path else 'Backup failed'}\n"
        f"**Instruction:** {instruction[:300]}\n"
        f"**Result:** {result[:300]}\n"
        f"---\n"
    )
    log_path = source_dir / "edit_log.md"
    try:
        existing = log_path.read_text() if log_path.exists() else "# Collab Chat Edit Log\n"
        log_path.write_text(existing + log_entry)
    except Exception:
        pass

    await websocket.send_json({
        "type": "dev_bar_edit_applied",
        "model": model_name,
        "result": result[:500],
    })
