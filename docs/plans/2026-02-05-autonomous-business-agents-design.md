# Autonomous Business Agent System — Design

## Goal

A fully autonomous multi-agent system that researches business opportunities, builds products, markets them, processes payments, and reinvests revenue — with minimal human intervention. Human approves spending over $20/action and receives daily reports.

## Architecture

CrewAI orchestrates a team of 5 specialized agents. Each agent uses a different AI model via the existing ai-mesh router. Langflow provides reusable AI pipelines (content generation, research, code deployment). n8n handles all external integrations (Stripe, email, Cloudflare, scheduling, notifications).

## Agent Team

| Agent | AI Model | Role | Tools |
|-------|----------|------|-------|
| Strategist | Claude Opus | Market research, opportunity evaluation, business planning, delegation | Web search, shared memory, task delegation |
| Researcher | Grok 3 | Deep dives, competitor analysis, trend monitoring, validation | SearXNG, web scraping, trend APIs |
| Builder | Claude Code | Build MVPs, deploy sites, set up infrastructure | Claude Code CLI, Vercel, Cloudflare Pages, GitHub |
| Marketer | GPT-4o | Copywriting, SEO, email sequences, social content, landing pages | Stable Diffusion, Resend email, content pipelines |
| Finance | Claude Sonnet | Budget tracking, pricing, Stripe setup, P&L, spending approval | Stripe API, PostgreSQL ledger, spending gates |

## Three-Layer Architecture

### Layer 1: CrewAI (Agent Brains) — Container :8120

- Defines agent roles, goals, backstories, and allowed tools
- Manages agent-to-agent delegation and conversation
- Maintains shared memory across agents via PostgreSQL
- All AI calls route through ai-mesh router at http://ai-mesh-router:8000
- Exposes REST API for triggering crews and checking status

### Layer 2: Langflow (AI Pipelines) — Existing :7860

Reusable pipelines that agents call as tools:

- **Content Pipeline**: prompt → GPT-4o draft → SEO optimize → generate hero image (Stable Diffusion) → return package
- **Research Pipeline**: query → SearXNG search → summarize results (Grok) → score opportunity → return report
- **Code Pipeline**: spec → Claude Code build → deploy to Vercel → test endpoints → return URL
- **Email Pipeline**: context → write email (GPT-4o) → send via Resend → log result

### Layer 3: n8n (External World) — Existing :5678

Event-driven workflows:

- **Stripe Webhooks**: payment_intent.succeeded → update ledger → notify Finance agent
- **Daily Strategy Session**: cron 9am → trigger CrewAI Strategist → run strategy review
- **Daily P&L Report**: cron 8pm → calculate revenue/costs → email summary to owner
- **Revenue Reinvestment**: cron midnight → calculate 10% of net → add to autonomous budget
- **Spending Approval**: Finance agent requests > $20 → push notification → wait for approval
- **Deploy Webhook**: Builder completes build → trigger Vercel/Cloudflare deploy
- **Health Monitor**: every 5min → check all agents alive → alert if down

## Database Schema (PostgreSQL — ai_mesh database)

### New tables (extend existing schema):

```sql
-- Active businesses the agents are running
businesses (
    id UUID PRIMARY KEY,
    name TEXT,
    description TEXT,
    status TEXT DEFAULT 'planning',  -- planning, building, launched, profitable, paused, shutdown
    business_type TEXT,              -- saas, digital_product, service, content
    stripe_product_id TEXT,
    domain TEXT,
    deploy_url TEXT,
    total_revenue NUMERIC DEFAULT 0,
    total_cost NUMERIC DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
)

-- Every decision logged with reasoning
decisions (
    id UUID PRIMARY KEY,
    business_id UUID REFERENCES businesses(id),
    agent TEXT,
    decision_type TEXT,              -- strategy, build, market, finance, research
    description TEXT,
    reasoning TEXT,
    outcome TEXT,
    cost NUMERIC DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
)

-- Budget ledger — every dollar tracked
budget_ledger (
    id UUID PRIMARY KEY,
    business_id UUID REFERENCES businesses(id),
    transaction_type TEXT,           -- expense, revenue, reinvestment, approval
    amount NUMERIC NOT NULL,
    description TEXT,
    agent TEXT,
    stripe_transaction_id TEXT,
    approved_by TEXT DEFAULT 'auto', -- 'auto' or 'human'
    created_at TIMESTAMP DEFAULT NOW()
)

-- Agent task queue
agent_tasks (
    id UUID PRIMARY KEY,
    business_id UUID REFERENCES businesses(id),
    agent TEXT,
    task_type TEXT,
    description TEXT,
    status TEXT DEFAULT 'pending',   -- pending, in_progress, completed, failed, blocked
    input_data JSONB DEFAULT '{}',
    output_data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
)

-- Shared memory — context all agents can read/write
shared_memory (
    id UUID PRIMARY KEY,
    key TEXT UNIQUE,
    value JSONB,
    agent TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
)
```

## Spending Rules

```
Per-action hard cap:        $20
Daily hard cap:             $100
Monthly hard cap:           $500

Revenue reinvestment:       10% of net revenue
├── Calculated nightly from Stripe balance
├── Added to "autonomous budget" pool in budget_ledger
└── Can spend from pool without human approval (still under $20/action)

Over $20 single action:     n8n sends push notification, blocks until approved
Over $100 daily total:      All spending blocked until human approves
Any Stripe payout change:   Logged + human notified

Kill switch:                ai-down (stops all containers)
Pause finance only:         ai-pause-finance (stops Finance agent)
```

## File Structure

```
/data/ai-mesh/
├── agents/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py              # FastAPI app exposing CrewAI endpoints
│   ├── crew.py              # Agent/crew definitions
│   ├── tools/
│   │   ├── search.py        # SearXNG web search
│   │   ├── stripe_tools.py  # Stripe payments/products
│   │   ├── email_tools.py   # Resend email
│   │   ├── deploy_tools.py  # Vercel/Cloudflare deploy
│   │   ├── domain_tools.py  # Cloudflare domain registration
│   │   ├── builder_tools.py # Claude Code integration
│   │   ├── memory_tools.py  # PostgreSQL shared memory
│   │   └── budget_tools.py  # Budget ledger + spending gates
│   └── config/
│       ├── agents.yaml      # Agent definitions
│       └── tasks.yaml       # Task templates
├── ... (existing proxy/router files)
```

## Container Additions

| Service | Port | Image | Purpose |
|---------|------|-------|---------|
| crewai-agents | 8120 | Custom Dockerfile | CrewAI agent orchestration |

Connects to: ai-mesh network + ai-stack network (for Ollama, Postgres)

## Typical Business Lifecycle

1. **Discovery** (Strategist + Researcher)
   - Strategist reviews market trends, asks Researcher for deep dives
   - Researcher returns scored opportunities with competitor analysis
   - Strategist picks top opportunity, writes business plan

2. **Build** (Builder + Finance)
   - Builder creates MVP (landing page + payment integration)
   - Finance sets up Stripe products, pricing, payment links
   - Builder deploys to Vercel/Cloudflare, buys domain if needed

3. **Launch** (Marketer + Builder)
   - Marketer creates content: blog posts, email sequences, social copy
   - Builder deploys content, sets up email automation via Resend
   - Marketer optimizes SEO, creates ad copy if budget allows

4. **Operate** (Finance + all agents)
   - n8n processes Stripe webhooks, updates revenue
   - Finance tracks P&L, calculates reinvestment
   - Strategist reviews performance weekly, pivots or doubles down
   - Marketer continuously creates content, tests messaging

5. **Scale or Pivot** (Strategist)
   - If profitable: Strategist allocates more budget, Marketer scales
   - If not working: Strategist analyzes why, pivots or shuts down
   - Freed budget goes to next opportunity

## Resource Requirements

- CrewAI container: CPU-only, ~500MB RAM
- No additional GPU needed (all AI through existing proxies)
- Total new overhead: ~500MB RAM, one new container
