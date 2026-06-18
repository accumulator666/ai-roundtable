# MeshCorp HQ — Phase 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace all 6 current roundtable UIs (ports 8130-8134, 8139) with a single MeshCorp HQ app — dynamic template-based team assembly, event-driven conversations, milestone-based project lifecycle, and a Svelte war-room dashboard.

**Architecture:** New FastAPI backend (`meshcorp/`) serves a Svelte SPA frontend. Templates define organization types (tech startup, hedge fund, law firm, etc.) and map roles to AI models. The event-driven conversation engine routes messages only to skill-matched participants. Projects follow milestone-based pipelines with go/no-go checkpoints. Reuses existing router (8110), proxies (8100-8105), Redis, PostgreSQL, Claude Code (8104), and CrewAI (8120).

**Tech Stack:** Python 3.12, FastAPI, asyncpg, redis, httpx, Pydantic v2 (backend). Svelte 5, Vite (frontend). PostgreSQL (ai_mesh DB). Redis (pub/sub, state). Docker Compose.

**Design Doc:** `docs/plans/2026-03-30-meshcorp-hq-design.md`

---

## Task 1: Scaffold the MeshCorp Backend

**Files:**
- Create: `meshcorp/__init__.py`
- Create: `meshcorp/main.py`
- Create: `meshcorp/requirements.txt`
- Create: `meshcorp/config.py`

**Step 1: Create directory structure**

```bash
mkdir -p /data/ai-mesh/meshcorp
```

**Step 2: Create requirements.txt**

Create `meshcorp/requirements.txt`:
```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
httpx>=0.27.0
pydantic>=2.10.0
asyncpg>=0.30.0
redis>=5.2.0
sse-starlette>=2.2.0
python-multipart>=0.0.18
```

**Step 3: Create config.py**

Create `meshcorp/config.py` — centralized settings loaded from env vars:
```python
import os

# Service URLs (internal Docker network)
ROUTER_URL = os.getenv("ROUTER_URL", "http://ai-mesh-router:8000")
CLAUDE_CODE_URL = os.getenv("CLAUDE_CODE_URL", "http://ai-mesh-claude-code:8000")
CREWAI_URL = os.getenv("AGENTS_URL", "http://ai-mesh-crewai:8000")

# Database
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "prompt-template-db")
POSTGRES_DB = os.getenv("POSTGRES_DB", "ai_mesh")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

# Redis
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Concurrency
MODEL_SEMAPHORE_LIMIT = int(os.getenv("MODEL_CONCURRENCY", "8"))

# Notifications
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY", "")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
OWNER_PHONE = os.getenv("OWNER_PHONE", "")
```

**Step 4: Create main.py skeleton**

Create `meshcorp/main.py` — minimal FastAPI app with health check and static file serving:
```python
import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

start_time = time.time()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init DB, Redis, load templates
    from meshcorp.db import init_db
    from meshcorp.templates import load_templates
    await init_db()
    load_templates()
    yield
    # Shutdown

app = FastAPI(title="MeshCorp HQ", lifespan=lifespan)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "meshcorp-hq",
        "uptime": round(time.time() - start_time),
    }

# Serve Svelte frontend (built to meshcorp/frontend/dist/)
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")

    @app.get("/{path:path}")
    async def serve_frontend(path: str):
        return FileResponse(os.path.join(frontend_dir, "index.html"))
```

**Step 5: Create __init__.py**

Create `meshcorp/__init__.py` (empty file).

**Step 6: Verify the skeleton starts**

```bash
cd /data/ai-mesh/meshcorp && pip install -r requirements.txt && python -c "from meshcorp.main import app; print('OK')"
```

**Step 7: Commit**

```bash
git add meshcorp/
git commit -m "feat(meshcorp): scaffold backend with config, main app skeleton"
```

---

## Task 2: Database Schema

**Files:**
- Create: `meshcorp/db.py`
- Create: `meshcorp/models.py`

**Step 1: Create Pydantic models**

Create `meshcorp/models.py` — all data models for the system:
```python
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
import uuid


class ProjectStatus(str, Enum):
    proposal = "proposal"        # AI-generated, awaiting approval
    planning = "planning"        # Approved, team assembling milestones
    active = "active"            # Executing milestones
    paused = "paused"            # Waiting on human action
    completed = "completed"
    killed = "killed"


class MilestoneStatus(str, Enum):
    pending = "pending"
    active = "active"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class ActionStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    dismissed = "dismissed"


class ActionUrgency(str, Enum):
    critical = "critical"    # Push to phone immediately
    normal = "normal"        # Dashboard inbox only


class MessageRole(str, Enum):
    user = "user"            # CEO (you)
    participant = "participant"
    system = "system"


# --- Template Models ---

class RoleDefinition(BaseModel):
    title: str
    model: str                           # model ID from router (e.g., "claude-code", "gpt-5.2", "deepseek-chat")
    persona: str                         # system prompt
    skills: list[str]                    # skill tags for event-driven routing
    color: str = "#6b7280"               # hex color for UI
    is_lead: bool = False                # team lead reviews others' work


class OrgTemplate(BaseModel):
    id: str
    name: str
    icon: str = "briefcase"
    description: str
    roles: list[RoleDefinition]
    default_milestones: list[str] = []
    skill_tags: list[str] = []          # all skills this template covers


# --- Project Models ---

class Milestone(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str
    description: str = ""
    deliverable: str = ""
    status: MilestoneStatus = MilestoneStatus.pending
    result: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class ProjectTeamMember(BaseModel):
    role: str                            # e.g., "Backend Dev"
    model: str                           # model ID
    persona: str                         # system prompt
    skills: list[str]
    color: str = "#6b7280"
    is_lead: bool = False


class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str
    description: str
    template_id: str                     # which org template was used
    status: ProjectStatus = ProjectStatus.planning
    team: list[ProjectTeamMember] = []
    milestones: list[Milestone] = []
    budget_allocated: float = 0.0
    budget_spent: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Conversation Models ---

class ConversationMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    project_id: str
    milestone_id: Optional[str] = None
    role: MessageRole
    participant_name: str = ""           # "Backend Dev", "CEO", "system"
    participant_model: str = ""          # model ID
    content: str
    skill_tags: list[str] = []           # what skills this message relates to
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# --- Action Queue ---

class HumanAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    project_id: str
    title: str                           # "Need Stripe API keys"
    description: str                     # Detailed instructions
    urgency: ActionUrgency = ActionUrgency.normal
    status: ActionStatus = ActionStatus.pending
    blocking_milestone: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


# --- API Request/Response ---

class CreateProjectRequest(BaseModel):
    template_id: str
    description: str = ""                # User's pitch. Empty = auto-generate
    model: str = "gpt-5.2"              # Model for planning


class ProjectResponse(BaseModel):
    project: Project
    messages: list[ConversationMessage] = []
    actions: list[HumanAction] = []


class FundProjectRequest(BaseModel):
    amount: float


class CEOMessageRequest(BaseModel):
    content: str
    directed_to: Optional[str] = None    # Specific role name, or None for all relevant
```

**Step 2: Create db.py**

Create `meshcorp/db.py` — async PostgreSQL with auto-schema:
```python
import asyncpg
import json
from meshcorp.config import POSTGRES_HOST, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

pool: asyncpg.Pool | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mc_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT DEFAULT 'briefcase',
    description TEXT,
    roles JSONB NOT NULL DEFAULT '[]',
    default_milestones JSONB DEFAULT '[]',
    skill_tags JSONB DEFAULT '[]',
    is_custom BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mc_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    template_id TEXT REFERENCES mc_templates(id),
    status TEXT DEFAULT 'planning',
    team JSONB NOT NULL DEFAULT '[]',
    budget_allocated NUMERIC(12,2) DEFAULT 0,
    budget_spent NUMERIC(12,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mc_milestones (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES mc_projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    deliverable TEXT,
    status TEXT DEFAULT 'pending',
    result TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mc_messages (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES mc_projects(id) ON DELETE CASCADE,
    milestone_id TEXT,
    role TEXT NOT NULL,
    participant_name TEXT,
    participant_model TEXT,
    content TEXT NOT NULL,
    skill_tags JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mc_actions (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES mc_projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    urgency TEXT DEFAULT 'normal',
    status TEXT DEFAULT 'pending',
    blocking_milestone TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mc_budget_ledger (
    id SERIAL PRIMARY KEY,
    project_id TEXT REFERENCES mc_projects(id) ON DELETE CASCADE,
    amount NUMERIC(12,2) NOT NULL,
    description TEXT,
    category TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mc_notifications (
    id SERIAL PRIMARY KEY,
    action_id TEXT,
    channel TEXT NOT NULL,
    status TEXT DEFAULT 'sent',
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


async def init_db():
    global pool
    pool = await asyncpg.create_pool(
        host=POSTGRES_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        min_size=2,
        max_size=10,
    )
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)


async def get_pool() -> asyncpg.Pool:
    if pool is None:
        await init_db()
    return pool
```

**Step 3: Verify schema creation**

```bash
cd /data/ai-mesh && python -c "
import asyncio
import sys
sys.path.insert(0, '.')
from meshcorp.db import init_db
asyncio.run(init_db())
print('Schema created OK')
"
```

**Step 4: Commit**

```bash
git add meshcorp/models.py meshcorp/db.py
git commit -m "feat(meshcorp): add database schema and Pydantic models"
```

---

## Task 3: Organization Templates

**Files:**
- Create: `meshcorp/templates.py`
- Create: `meshcorp/templates/tech-startup.json`
- Create: `meshcorp/templates/hedge-fund.json`
- Create: `meshcorp/templates/law-firm.json`
- Create: `meshcorp/templates/marketing-agency.json`
- Create: `meshcorp/templates/research-lab.json`
- Create: `meshcorp/templates/ecommerce.json`
- Create: `meshcorp/templates/consulting.json`

**Step 1: Create template loader**

Create `meshcorp/templates.py`:
```python
import os
import json
from meshcorp.models import OrgTemplate

TEMPLATES: dict[str, OrgTemplate] = {}
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def load_templates():
    """Load all template JSON files from templates/ directory."""
    global TEMPLATES
    TEMPLATES.clear()
    for filename in os.listdir(TEMPLATE_DIR):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(TEMPLATE_DIR, filename)
        with open(filepath) as f:
            data = json.load(f)
        template = OrgTemplate(**data)
        TEMPLATES[template.id] = template


def get_template(template_id: str) -> OrgTemplate | None:
    return TEMPLATES.get(template_id)


def list_templates() -> list[OrgTemplate]:
    return list(TEMPLATES.values())
```

**Step 2: Create template JSON files**

Create `meshcorp/templates/` directory, then create each template. Key principle: map roles to the **best available model** from the router's MODEL_TO_PROXY dict, and use free/cheap R730 models for grunt work.

`meshcorp/templates/tech-startup.json`:
```json
{
  "id": "tech-startup",
  "name": "Tech Startup",
  "icon": "rocket",
  "description": "Full-stack product team for building and shipping software products",
  "roles": [
    {
      "title": "Tech Lead",
      "model": "claude-sonnet-4-5",
      "persona": "You are a senior staff engineer and tech lead. You review all code and architecture decisions. You ensure quality, security, and maintainability. You approve or reject work from other engineers with specific, actionable feedback. You make final technical decisions when the team disagrees.",
      "skills": ["architecture", "code_review", "technical_decisions", "backend", "frontend", "security"],
      "color": "#3b82f6",
      "is_lead": true
    },
    {
      "title": "Frontend Dev",
      "model": "gpt-5.2",
      "persona": "You are a senior frontend developer. You build responsive, accessible UIs with modern frameworks (React, Svelte, Vue). You write clean component code, handle state management, and ensure great UX. You work from design specs and product requirements.",
      "skills": ["frontend", "ui", "css", "accessibility", "components"],
      "color": "#8b5cf6"
    },
    {
      "title": "Backend Dev",
      "model": "claude-sonnet-4-5",
      "persona": "You are a senior backend developer. You design APIs, database schemas, and server-side logic. You write efficient, secure, and well-tested code. You handle authentication, data validation, and integration with external services.",
      "skills": ["backend", "api", "database", "authentication", "infrastructure"],
      "color": "#06b6d4"
    },
    {
      "title": "DevOps Engineer",
      "model": "grok-3-mini",
      "persona": "You are a DevOps engineer. You set up CI/CD pipelines, Docker containers, deployment automation, monitoring, and infrastructure. You ensure reliability, scalability, and security of the production environment.",
      "skills": ["devops", "docker", "ci_cd", "monitoring", "infrastructure", "deployment"],
      "color": "#f59e0b"
    },
    {
      "title": "Product Manager",
      "model": "gpt-5.2",
      "persona": "You are a product manager. You define product requirements, user stories, and acceptance criteria. You prioritize features based on user value and business impact. You coordinate between engineering, design, and business stakeholders.",
      "skills": ["product", "requirements", "user_stories", "prioritization", "roadmap"],
      "color": "#ec4899"
    },
    {
      "title": "Designer",
      "model": "gemini-2.0-flash",
      "persona": "You are a product designer. You create UI/UX designs, wireframes, and user flows. You think about usability, accessibility, and visual consistency. You provide design specs that developers can implement.",
      "skills": ["design", "ui", "ux", "wireframes", "visual"],
      "color": "#a855f7"
    },
    {
      "title": "QA Engineer",
      "model": "deepseek-chat",
      "persona": "You are a QA engineer. You write test plans, find edge cases, and verify functionality works correctly. You think about what could break and test those scenarios. You report bugs with clear reproduction steps.",
      "skills": ["testing", "qa", "edge_cases", "bugs", "test_plans"],
      "color": "#22c55e"
    }
  ],
  "default_milestones": [
    "Market validation and competitive analysis",
    "Technical architecture and design",
    "MVP implementation",
    "Testing and QA",
    "Launch and initial marketing"
  ],
  "skill_tags": ["frontend", "backend", "devops", "product", "design", "testing", "architecture", "api", "database", "deployment"]
}
```

`meshcorp/templates/hedge-fund.json`:
```json
{
  "id": "hedge-fund",
  "name": "Hedge Fund",
  "icon": "chart",
  "description": "Quantitative trading and investment management team",
  "roles": [
    {
      "title": "Portfolio Manager",
      "model": "claude-sonnet-4-5",
      "persona": "You are a senior portfolio manager. You make final investment decisions, manage position sizing, and oversee risk-adjusted returns. You evaluate trade ideas from the team and approve or reject them with clear reasoning.",
      "skills": ["portfolio", "investment_decisions", "position_sizing", "strategy"],
      "color": "#10b981",
      "is_lead": true
    },
    {
      "title": "Quant Analyst",
      "model": "deepseek-reasoner",
      "persona": "You are a quantitative analyst. You build mathematical models for pricing, risk, and alpha generation. You analyze statistical patterns, run backtests, and provide quantitative evidence for trade ideas.",
      "skills": ["quantitative", "modeling", "backtesting", "statistics", "math", "data_analysis"],
      "color": "#6366f1"
    },
    {
      "title": "Risk Manager",
      "model": "gpt-5.2",
      "persona": "You are a risk manager. You identify, measure, and monitor portfolio risks. You set position limits, calculate VaR, stress test scenarios, and flag concentration risks. You are conservative and protect capital above all.",
      "skills": ["risk", "compliance", "limits", "stress_testing", "var"],
      "color": "#ef4444"
    },
    {
      "title": "Market Researcher",
      "model": "grok-3",
      "persona": "You are a market researcher with real-time market awareness. You analyze macro trends, sector rotations, earnings, news flow, and sentiment. You identify catalysts and provide actionable market intelligence.",
      "skills": ["market_research", "macro", "news", "sentiment", "catalysts", "trends"],
      "color": "#f59e0b"
    },
    {
      "title": "Data Engineer",
      "model": "deepseek-chat",
      "persona": "You are a data engineer. You build data pipelines, clean datasets, set up databases for market data, and automate data collection. You ensure the team has reliable, timely data for analysis and trading.",
      "skills": ["data_engineering", "pipelines", "database", "automation", "etl"],
      "color": "#06b6d4"
    },
    {
      "title": "Compliance Officer",
      "model": "claude-sonnet-4-5",
      "persona": "You are a compliance officer. You ensure all trading activities comply with regulations. You review trades for insider trading risk, position limit violations, and reporting requirements. You flag issues before they become problems.",
      "skills": ["compliance", "regulation", "legal", "reporting", "audit"],
      "color": "#64748b"
    }
  ],
  "default_milestones": [
    "Strategy thesis and market analysis",
    "Data pipeline and model development",
    "Backtesting and validation",
    "Paper trading and risk framework",
    "Live deployment with position limits"
  ],
  "skill_tags": ["portfolio", "quantitative", "risk", "market_research", "data_engineering", "compliance", "trading"]
}
```

`meshcorp/templates/law-firm.json`:
```json
{
  "id": "law-firm",
  "name": "Law Firm",
  "icon": "scale",
  "description": "Legal team for contracts, compliance, IP, and business law",
  "roles": [
    {
      "title": "Senior Partner",
      "model": "claude-sonnet-4-5",
      "persona": "You are a senior partner at a law firm. You oversee all legal matters, make final decisions on strategy, review work product from associates, and advise clients on complex legal issues. You have deep expertise across corporate, IP, and regulatory law.",
      "skills": ["legal_strategy", "client_advisory", "litigation", "corporate_law", "review"],
      "color": "#1e3a5f",
      "is_lead": true
    },
    {
      "title": "Associate Attorney",
      "model": "gpt-5.2",
      "persona": "You are an associate attorney. You draft legal documents, research case law, prepare briefs, and analyze legal risks. You support the senior partner with thorough, well-cited legal work.",
      "skills": ["legal_research", "drafting", "briefs", "case_law", "analysis"],
      "color": "#3b82f6"
    },
    {
      "title": "Paralegal",
      "model": "deepseek-chat",
      "persona": "You are an experienced paralegal. You organize case files, prepare discovery documents, manage deadlines, and handle high-volume document review. You are detail-oriented and efficient.",
      "skills": ["document_review", "filing", "discovery", "organization", "deadlines"],
      "color": "#8b5cf6"
    },
    {
      "title": "Legal Researcher",
      "model": "grok-3",
      "persona": "You are a legal researcher. You find relevant statutes, case precedents, regulatory guidance, and legal commentary. You provide comprehensive research memos with citations.",
      "skills": ["legal_research", "statutes", "precedent", "regulatory", "citations"],
      "color": "#f59e0b"
    },
    {
      "title": "Contract Specialist",
      "model": "claude-sonnet-4-5",
      "persona": "You are a contract specialist. You draft, review, and negotiate contracts. You identify unfavorable terms, suggest protective clauses, and ensure contracts align with business objectives and legal requirements.",
      "skills": ["contracts", "negotiation", "terms", "drafting", "review"],
      "color": "#06b6d4"
    }
  ],
  "default_milestones": [
    "Legal situation assessment and research",
    "Strategy development and risk analysis",
    "Document drafting and review",
    "Negotiation and revision",
    "Finalization and filing"
  ],
  "skill_tags": ["legal_strategy", "legal_research", "contracts", "compliance", "litigation", "corporate_law"]
}
```

`meshcorp/templates/marketing-agency.json`:
```json
{
  "id": "marketing-agency",
  "name": "Marketing Agency",
  "icon": "megaphone",
  "description": "Full-service marketing team for campaigns, content, and growth",
  "roles": [
    {
      "title": "Creative Director",
      "model": "gpt-5.2",
      "persona": "You are a creative director. You develop campaign concepts, brand voice, and creative strategy. You review all creative work for quality and brand consistency. You have a strong eye for what resonates with audiences.",
      "skills": ["creative_strategy", "branding", "campaigns", "review", "brand_voice"],
      "color": "#ec4899",
      "is_lead": true
    },
    {
      "title": "Copywriter",
      "model": "claude-sonnet-4-5",
      "persona": "You are a senior copywriter. You write compelling copy for ads, landing pages, emails, social media, and content marketing. You adapt tone and style to different audiences and platforms.",
      "skills": ["copywriting", "content", "ads", "email", "landing_pages", "social_media"],
      "color": "#8b5cf6"
    },
    {
      "title": "SEO Specialist",
      "model": "deepseek-chat",
      "persona": "You are an SEO specialist. You research keywords, analyze search intent, optimize content for rankings, and track performance metrics. You provide data-driven recommendations for organic growth.",
      "skills": ["seo", "keywords", "analytics", "organic_growth", "content_optimization"],
      "color": "#22c55e"
    },
    {
      "title": "Social Media Manager",
      "model": "grok-3-mini",
      "persona": "You are a social media manager. You create platform-specific content strategies, engage with audiences, track trends, and optimize posting schedules. You understand each platform's algorithm and audience behavior.",
      "skills": ["social_media", "engagement", "trends", "platform_strategy", "community"],
      "color": "#06b6d4"
    },
    {
      "title": "Growth Marketer",
      "model": "gpt-5.2",
      "persona": "You are a growth marketer. You design and run experiments to acquire and retain users. You analyze funnels, optimize conversion rates, manage paid campaigns, and identify the highest-ROI growth channels.",
      "skills": ["growth", "acquisition", "conversion", "paid_ads", "funnels", "analytics"],
      "color": "#f59e0b"
    },
    {
      "title": "Graphic Designer",
      "model": "gemini-2.0-flash",
      "persona": "You are a graphic designer. You create visual assets for campaigns — social media graphics, ad creatives, presentations, and brand materials. You work from brand guidelines and creative briefs.",
      "skills": ["design", "graphics", "visual", "brand_materials", "ads"],
      "color": "#a855f7"
    }
  ],
  "default_milestones": [
    "Market research and audience analysis",
    "Brand strategy and creative brief",
    "Content and asset creation",
    "Campaign launch and distribution",
    "Performance analysis and optimization"
  ],
  "skill_tags": ["creative_strategy", "copywriting", "seo", "social_media", "growth", "design", "branding"]
}
```

`meshcorp/templates/research-lab.json`:
```json
{
  "id": "research-lab",
  "name": "Research Lab",
  "icon": "microscope",
  "description": "Deep research and analysis team for complex investigations",
  "roles": [
    {
      "title": "Principal Researcher",
      "model": "claude-sonnet-4-5",
      "persona": "You are a principal researcher leading a research team. You define research questions, evaluate methodology, synthesize findings, and ensure rigor. You challenge weak arguments and demand evidence.",
      "skills": ["research_strategy", "methodology", "synthesis", "review", "analysis"],
      "color": "#3b82f6",
      "is_lead": true
    },
    {
      "title": "Data Scientist",
      "model": "deepseek-reasoner",
      "persona": "You are a data scientist. You analyze datasets, build models, run experiments, and extract insights from data. You communicate findings clearly with visualizations and statistical evidence.",
      "skills": ["data_analysis", "statistics", "modeling", "experiments", "visualization"],
      "color": "#06b6d4"
    },
    {
      "title": "Domain Expert",
      "model": "gpt-5.2",
      "persona": "You are a domain expert with broad knowledge across technology, science, business, and social systems. You provide context, identify relevant frameworks, and connect findings to real-world applications.",
      "skills": ["domain_knowledge", "frameworks", "context", "applications", "interdisciplinary"],
      "color": "#f59e0b"
    },
    {
      "title": "Research Analyst",
      "model": "grok-3",
      "persona": "You are a research analyst. You gather information from diverse sources, fact-check claims, compile literature reviews, and identify gaps in existing knowledge. You are thorough and skeptical.",
      "skills": ["research", "fact_checking", "literature_review", "sources", "information_gathering"],
      "color": "#22c55e"
    },
    {
      "title": "Technical Writer",
      "model": "deepseek-chat",
      "persona": "You are a technical writer. You turn complex research into clear, well-structured documents — reports, white papers, executive summaries, and presentations. You make complex topics accessible.",
      "skills": ["writing", "documentation", "reports", "summaries", "presentations"],
      "color": "#8b5cf6"
    }
  ],
  "default_milestones": [
    "Research question definition and literature review",
    "Data collection and methodology design",
    "Analysis and experimentation",
    "Findings synthesis and validation",
    "Final report and recommendations"
  ],
  "skill_tags": ["research_strategy", "data_analysis", "domain_knowledge", "writing", "methodology"]
}
```

`meshcorp/templates/ecommerce.json`:
```json
{
  "id": "ecommerce",
  "name": "E-Commerce",
  "icon": "cart",
  "description": "Online retail team for building and scaling e-commerce businesses",
  "roles": [
    {
      "title": "E-Commerce Director",
      "model": "gpt-5.2",
      "persona": "You are an e-commerce director. You oversee the entire online retail operation — product selection, pricing, storefront, fulfillment, and customer experience. You make strategic decisions to maximize revenue and customer satisfaction.",
      "skills": ["ecommerce_strategy", "pricing", "operations", "customer_experience", "review"],
      "color": "#10b981",
      "is_lead": true
    },
    {
      "title": "Storefront Developer",
      "model": "claude-sonnet-4-5",
      "persona": "You are a storefront developer. You build and customize online stores — product pages, checkout flows, payment integration, and responsive design. You optimize for conversion and page speed.",
      "skills": ["frontend", "storefront", "checkout", "payments", "conversion_optimization"],
      "color": "#3b82f6"
    },
    {
      "title": "Product Analyst",
      "model": "deepseek-chat",
      "persona": "You are a product analyst for e-commerce. You research market demand, analyze competitor pricing, identify trending products, and recommend inventory decisions based on data.",
      "skills": ["product_research", "market_analysis", "pricing", "trends", "inventory"],
      "color": "#f59e0b"
    },
    {
      "title": "Marketing Specialist",
      "model": "grok-3-mini",
      "persona": "You are an e-commerce marketing specialist. You create product listings, write descriptions, manage email campaigns, run promotions, and optimize for marketplace algorithms (Amazon, Etsy, Shopify).",
      "skills": ["product_marketing", "listings", "email", "promotions", "marketplace"],
      "color": "#ec4899"
    },
    {
      "title": "Operations Manager",
      "model": "deepseek-chat",
      "persona": "You are an operations manager. You handle logistics, fulfillment, inventory management, supplier relationships, and cost optimization. You ensure smooth order processing and delivery.",
      "skills": ["operations", "logistics", "fulfillment", "inventory", "suppliers"],
      "color": "#64748b"
    }
  ],
  "default_milestones": [
    "Market research and product selection",
    "Store setup and product listing",
    "Payment and fulfillment integration",
    "Launch and initial marketing",
    "Optimization and scaling"
  ],
  "skill_tags": ["ecommerce_strategy", "storefront", "product_research", "product_marketing", "operations"]
}
```

`meshcorp/templates/consulting.json`:
```json
{
  "id": "consulting",
  "name": "Consulting Firm",
  "icon": "users",
  "description": "Strategy and management consulting team for client engagements",
  "roles": [
    {
      "title": "Engagement Manager",
      "model": "claude-sonnet-4-5",
      "persona": "You are an engagement manager at a top consulting firm. You lead client engagements, structure problem-solving, manage deliverables, and present findings. You ensure the team delivers actionable, high-quality recommendations.",
      "skills": ["engagement_management", "problem_solving", "client_relations", "presentations", "review"],
      "color": "#1e3a5f",
      "is_lead": true
    },
    {
      "title": "Strategy Consultant",
      "model": "gpt-5.2",
      "persona": "You are a strategy consultant. You analyze business problems, develop frameworks, evaluate options, and build strategic recommendations. You think in terms of competitive advantage, market positioning, and value creation.",
      "skills": ["strategy", "frameworks", "competitive_analysis", "market_positioning", "business_cases"],
      "color": "#3b82f6"
    },
    {
      "title": "Financial Analyst",
      "model": "deepseek-reasoner",
      "persona": "You are a financial analyst. You build financial models, analyze unit economics, project revenue and costs, and evaluate ROI. You provide the quantitative backbone for strategic recommendations.",
      "skills": ["financial_modeling", "unit_economics", "projections", "roi", "valuation"],
      "color": "#10b981"
    },
    {
      "title": "Industry Researcher",
      "model": "grok-3",
      "persona": "You are an industry researcher. You gather market data, benchmark competitors, analyze industry trends, and provide the factual foundation for consulting recommendations.",
      "skills": ["industry_research", "benchmarking", "market_data", "trends", "competitive_intelligence"],
      "color": "#f59e0b"
    },
    {
      "title": "Implementation Specialist",
      "model": "deepseek-chat",
      "persona": "You are an implementation specialist. You turn strategic recommendations into actionable implementation plans with timelines, resource requirements, risk mitigation, and success metrics.",
      "skills": ["implementation", "project_planning", "change_management", "risk_mitigation", "metrics"],
      "color": "#8b5cf6"
    }
  ],
  "default_milestones": [
    "Problem definition and scoping",
    "Research and data gathering",
    "Analysis and hypothesis testing",
    "Recommendation development",
    "Implementation roadmap and handoff"
  ],
  "skill_tags": ["strategy", "financial_modeling", "industry_research", "implementation", "problem_solving"]
}
```

**Step 3: Verify templates load**

```bash
cd /data/ai-mesh && python -c "
import sys; sys.path.insert(0, '.')
from meshcorp.templates import load_templates, list_templates
load_templates()
for t in list_templates():
    print(f'{t.id}: {t.name} ({len(t.roles)} roles)')
"
```

Expected output:
```
tech-startup: Tech Startup (7 roles)
hedge-fund: Hedge Fund (6 roles)
law-firm: Law Firm (5 roles)
marketing-agency: Marketing Agency (6 roles)
research-lab: Research Lab (5 roles)
ecommerce: E-Commerce (5 roles)
consulting: Consulting Firm (5 roles)
```

**Step 4: Commit**

```bash
git add meshcorp/templates.py meshcorp/templates/
git commit -m "feat(meshcorp): add 7 organization templates with role-to-model mappings"
```

---

## Task 4: Event-Driven Conversation Engine

**Files:**
- Create: `meshcorp/conversation.py`

This is the core differentiator — messages are routed only to participants whose skills match, not broadcast to everyone.

**Step 1: Create conversation engine**

Create `meshcorp/conversation.py`:
```python
"""
Event-driven conversation engine.

Unlike the old roundtable (fire-all-parallel), this engine:
1. Analyzes each message for skill tags
2. Routes only to participants whose skills overlap
3. Participants respond sequentially (each sees prior responses)
4. New skill tags in responses can pull in additional participants
5. Lead/reviewer has final say on decisions
"""

import asyncio
import re
import json
import httpx
import time
from meshcorp.config import ROUTER_URL, MODEL_SEMAPHORE_LIMIT
from meshcorp.models import ProjectTeamMember, ConversationMessage, MessageRole

MODEL_SEMAPHORE = asyncio.Semaphore(MODEL_SEMAPHORE_LIMIT)

# Keyword -> skill tag mapping for auto-tagging messages
SKILL_KEYWORDS: dict[str, list[str]] = {
    "frontend": ["react", "svelte", "vue", "css", "ui", "ux", "component", "responsive", "layout", "html", "tailwind"],
    "backend": ["api", "server", "endpoint", "database", "sql", "rest", "graphql", "auth", "jwt", "session"],
    "devops": ["docker", "ci", "cd", "deploy", "pipeline", "kubernetes", "nginx", "monitoring", "infrastructure"],
    "security": ["security", "vulnerability", "oauth", "encryption", "xss", "csrf", "injection", "rate limit"],
    "testing": ["test", "qa", "bug", "edge case", "regression", "coverage", "assertion"],
    "design": ["design", "wireframe", "mockup", "prototype", "color", "typography", "layout", "figma"],
    "product": ["requirement", "user story", "acceptance criteria", "priorit", "roadmap", "feature", "mvp"],
    "architecture": ["architecture", "system design", "scalab", "microservice", "monolith", "pattern", "tradeoff"],
    "database": ["schema", "migration", "index", "query", "postgres", "redis", "table", "relation"],
    "legal_strategy": ["legal", "law", "regulation", "compliance", "liability", "court", "statute"],
    "contracts": ["contract", "clause", "agreement", "terms", "negotiate", "sign"],
    "legal_research": ["case law", "precedent", "statute", "citation", "ruling"],
    "portfolio": ["portfolio", "position", "allocation", "rebalance", "diversif"],
    "quantitative": ["model", "backtest", "alpha", "signal", "factor", "regression", "statistics"],
    "risk": ["risk", "var", "drawdown", "stress test", "exposure", "hedge", "limit"],
    "market_research": ["market", "competitor", "trend", "demand", "customer", "segment", "tam"],
    "copywriting": ["copy", "headline", "cta", "landing page", "email", "ad copy", "tagline"],
    "seo": ["seo", "keyword", "ranking", "organic", "search", "backlink", "meta"],
    "social_media": ["social", "instagram", "twitter", "tiktok", "linkedin", "engagement", "follower"],
    "growth": ["growth", "acquisition", "retention", "funnel", "conversion", "churn", "ltv", "cac"],
    "financial_modeling": ["revenue", "cost", "margin", "projections", "unit economics", "p&l", "forecast"],
    "pricing": ["pricing", "price point", "discount", "subscription", "freemium", "tier"],
    "strategy": ["strategy", "competitive advantage", "positioning", "vision", "mission", "goal"],
    "ecommerce_strategy": ["ecommerce", "store", "shopify", "amazon", "etsy", "product listing", "checkout"],
    "data_analysis": ["data", "analytics", "metrics", "dashboard", "report", "insight", "kpi"],
    "operations": ["operations", "logistics", "fulfillment", "shipping", "inventory", "supply chain"],
    "creative_strategy": ["campaign", "brand", "creative", "storytelling", "narrative", "audience"],
    "research": ["research", "investigation", "literature", "survey", "methodology", "hypothesis"],
    "writing": ["write", "document", "report", "white paper", "summary", "presentation"],
}


def extract_skill_tags(text: str) -> list[str]:
    """Extract skill tags from message content based on keyword matching."""
    text_lower = text.lower()
    matched = set()
    for skill, keywords in SKILL_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                matched.add(skill)
                break
    return list(matched)


def match_participants(
    skill_tags: list[str],
    team: list[ProjectTeamMember],
    include_lead: bool = False,
) -> list[ProjectTeamMember]:
    """Return participants whose skills overlap with the given tags."""
    matched = []
    for member in team:
        member_skills = set(member.skills)
        if member_skills & set(skill_tags):
            matched.append(member)
        elif include_lead and member.is_lead:
            matched.append(member)
    # If nothing matched, fall back to the lead
    if not matched:
        leads = [m for m in team if m.is_lead]
        matched = leads if leads else [team[0]]
    return matched


async def call_model(
    model_id: str,
    messages: list[dict],
    max_tokens: int = 2048,
    temperature: float = 0.7,
    timeout: float = 120.0,
) -> str:
    """Call a model via the AI Router. Returns response text or error string."""
    async with MODEL_SEMAPHORE:
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(
                    f"{ROUTER_URL}/v1/chat/completions",
                    json={
                        "model": model_id,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except Exception as e:
                return f"[Error calling {model_id}: {e}]"


async def run_discussion(
    topic: str,
    team: list[ProjectTeamMember],
    project_context: str = "",
    history: list[ConversationMessage] | None = None,
    on_message=None,
    max_rounds: int = 3,
) -> list[ConversationMessage]:
    """
    Run an event-driven discussion on a topic.

    1. Extract skill tags from the topic
    2. Route to matching participants
    3. Each responds sequentially, seeing prior responses
    4. New tags in responses may pull in more participants
    5. Lead reviews at end if they haven't spoken

    Args:
        topic: The message/question to discuss
        team: All team members for this project
        project_context: Background info about the project
        history: Prior conversation messages for context
        on_message: async callback(ConversationMessage) for real-time streaming to UI
        max_rounds: Max discussion rounds (each round = one pass through matched participants)

    Returns:
        List of new ConversationMessage objects from this discussion
    """
    messages: list[ConversationMessage] = []
    all_tags = set(extract_skill_tags(topic))
    responded = set()  # track who already spoke

    for round_num in range(max_rounds):
        participants = match_participants(
            list(all_tags),
            team,
            include_lead=(round_num > 0),  # pull in lead after round 1
        )

        # Filter to those who haven't responded yet (unless round 2+ where they respond to new info)
        if round_num == 0:
            to_speak = [p for p in participants if p.role not in responded]
        else:
            # In later rounds, only speak if there are new tags they match
            to_speak = [p for p in participants if p.role not in responded or round_num > 0]

        if not to_speak:
            break

        new_tags_this_round = set()

        for participant in to_speak:
            # Build message context for this participant
            system_prompt = participant.persona
            if project_context:
                system_prompt += f"\n\nProject context: {project_context}"

            llm_messages = [{"role": "system", "content": system_prompt}]

            # Add relevant history (last 20 messages)
            if history:
                for h in history[-20:]:
                    role = "assistant" if h.role == MessageRole.participant else "user"
                    llm_messages.append({
                        "role": role,
                        "content": f"[{h.participant_name}]: {h.content}" if h.participant_name else h.content,
                    })

            # Add messages from this discussion so far
            for m in messages:
                role = "assistant" if m.participant_name == participant.role else "user"
                llm_messages.append({
                    "role": role,
                    "content": f"[{m.participant_name}]: {m.content}",
                })

            # Add the current topic if this is the first message
            if not messages:
                llm_messages.append({"role": "user", "content": topic})
            elif round_num > 0 and participant.role in responded:
                # Participant already spoke — ask them to respond to new discussion
                llm_messages.append({
                    "role": "user",
                    "content": "Based on the discussion above, do you have anything to add or revise? If not, say PASS.",
                })

            # Call the model
            response = await call_model(participant.model, llm_messages)

            # Skip if participant passes
            if response.strip().upper() == "PASS":
                continue

            # Create message record
            msg = ConversationMessage(
                project_id="",  # filled by caller
                role=MessageRole.participant,
                participant_name=participant.role,
                participant_model=participant.model,
                content=response,
                skill_tags=extract_skill_tags(response),
            )
            messages.append(msg)
            responded.add(participant.role)

            # Extract new skill tags from response
            response_tags = set(extract_skill_tags(response))
            new_tags_this_round |= response_tags - all_tags

            # Stream to UI if callback provided
            if on_message:
                await on_message(msg)

        # Add new tags for next round routing
        all_tags |= new_tags_this_round

        # If no new tags were introduced, we're done
        if not new_tags_this_round and round_num > 0:
            break

    # Final: if lead hasn't spoken, ask for their review/decision
    leads = [m for m in team if m.is_lead and m.role not in responded]
    for lead in leads:
        system_prompt = lead.persona + "\n\nReview the discussion above and provide your decision or synthesis."
        if project_context:
            system_prompt += f"\n\nProject context: {project_context}"

        llm_messages = [{"role": "system", "content": system_prompt}]
        for m in messages:
            llm_messages.append({
                "role": "user",
                "content": f"[{m.participant_name}]: {m.content}",
            })
        llm_messages.append({
            "role": "user",
            "content": "As the team lead, review the above discussion and provide your decision, synthesis, or action items.",
        })

        response = await call_model(lead.model, llm_messages)
        msg = ConversationMessage(
            project_id="",
            role=MessageRole.participant,
            participant_name=lead.role,
            participant_model=lead.model,
            content=response,
            skill_tags=extract_skill_tags(response),
        )
        messages.append(msg)
        if on_message:
            await on_message(msg)

    return messages
```

**Step 2: Verify the module imports cleanly**

```bash
cd /data/ai-mesh && python -c "
import sys; sys.path.insert(0, '.')
from meshcorp.conversation import extract_skill_tags, match_participants
tags = extract_skill_tags('We need a REST API with JWT auth and a React frontend')
print('Tags:', tags)
"
```

Expected: Tags include `backend`, `security`, `frontend` (at minimum).

**Step 3: Commit**

```bash
git add meshcorp/conversation.py
git commit -m "feat(meshcorp): event-driven conversation engine with skill-based routing"
```

---

## Task 5: Project Lifecycle Manager

**Files:**
- Create: `meshcorp/projects.py`

**Step 1: Create project manager**

Create `meshcorp/projects.py` — handles the full project lifecycle from creation through milestone execution:
```python
"""
Project lifecycle manager.

Handles: create project from template -> team assembly -> milestone planning ->
milestone execution (via conversation engine) -> checkpoint reporting -> completion.
"""

import json
import uuid
from datetime import datetime
from meshcorp.models import (
    Project, ProjectStatus, Milestone, MilestoneStatus,
    ProjectTeamMember, HumanAction, ActionUrgency, ConversationMessage, MessageRole,
)
from meshcorp.templates import get_template
from meshcorp.conversation import run_discussion, call_model
from meshcorp.db import get_pool


# --- Project CRUD ---

async def create_project(template_id: str, description: str, model: str = "gpt-5.2") -> Project:
    """Create a new project from a template. If description is empty, AI generates an idea."""
    template = get_template(template_id)
    if not template:
        raise ValueError(f"Unknown template: {template_id}")

    # Assemble team from template roles
    team = [
        ProjectTeamMember(
            role=role.title,
            model=role.model,
            persona=role.persona,
            skills=role.skills,
            color=role.color,
            is_lead=role.is_lead,
        )
        for role in template.roles
    ]

    project_id = str(uuid.uuid4())[:8]

    # If no description, ask AI to generate a project idea
    if not description:
        idea_prompt = f"""You are a {template.name} executive. Propose one specific, actionable project idea
that a {template.name} could execute profitably. Be concrete — name the product/service,
target customer, and how it makes money. Respond with just the project pitch in 2-3 sentences."""
        description = await call_model(model, [
            {"role": "system", "content": f"You generate business ideas for a {template.name}."},
            {"role": "user", "content": idea_prompt},
        ])

    # Ask AI to generate milestones specific to this project
    milestone_prompt = f"""Given this project for a {template.name}:

{description}

Generate 4-7 milestones for executing this project. Each milestone should have a clear deliverable.
Respond in JSON format:
[
  {{"title": "milestone name", "description": "what to do", "deliverable": "tangible output"}}
]

Only respond with the JSON array, no other text."""

    milestones_raw = await call_model(model, [
        {"role": "system", "content": "You are a project planner. Respond only with valid JSON."},
        {"role": "user", "content": milestone_prompt},
    ])

    # Parse milestones
    try:
        # Strip markdown code fences if present
        clean = milestones_raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1].rsplit("```", 1)[0]
        milestone_data = json.loads(clean)
    except (json.JSONDecodeError, IndexError):
        # Fall back to template defaults
        milestone_data = [
            {"title": m, "description": "", "deliverable": ""}
            for m in template.default_milestones
        ]

    milestones = [
        Milestone(
            id=str(uuid.uuid4())[:8],
            title=m.get("title", ""),
            description=m.get("description", ""),
            deliverable=m.get("deliverable", ""),
        )
        for i, m in enumerate(milestone_data)
    ]

    # Generate project name
    name_prompt = f"Give a short, catchy project name (2-4 words) for: {description[:200]}. Respond with just the name."
    name = await call_model(model, [
        {"role": "user", "content": name_prompt},
    ])
    name = name.strip().strip('"').strip("'")[:60]

    project = Project(
        id=project_id,
        name=name,
        description=description,
        template_id=template_id,
        status=ProjectStatus.planning,
        team=team,
        milestones=milestones,
    )

    # Persist to DB
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO mc_projects (id, name, description, template_id, status, team)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            project.id, project.name, project.description,
            project.template_id, project.status.value,
            json.dumps([m.model_dump() for m in project.team]),
        )
        for i, ms in enumerate(project.milestones):
            await conn.execute(
                """INSERT INTO mc_milestones (id, project_id, title, description, deliverable, sort_order)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                ms.id, project.id, ms.title, ms.description, ms.deliverable, i,
            )

    return project


async def get_project(project_id: str) -> Project | None:
    """Load a project with its milestones from DB."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM mc_projects WHERE id = $1", project_id)
        if not row:
            return None

        milestones_rows = await conn.fetch(
            "SELECT * FROM mc_milestones WHERE project_id = $1 ORDER BY sort_order", project_id
        )

        team = [ProjectTeamMember(**m) for m in json.loads(row["team"])]
        milestones = [
            Milestone(
                id=r["id"],
                title=r["title"],
                description=r["description"] or "",
                deliverable=r["deliverable"] or "",
                status=MilestoneStatus(r["status"]),
                result=r["result"] or "",
                completed_at=r["completed_at"],
            )
            for r in milestones_rows
        ]

        return Project(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            template_id=row["template_id"],
            status=ProjectStatus(row["status"]),
            team=team,
            milestones=milestones,
            budget_allocated=float(row["budget_allocated"]),
            budget_spent=float(row["budget_spent"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


async def list_projects(status: str | None = None) -> list[Project]:
    """List all projects, optionally filtered by status."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                "SELECT id FROM mc_projects WHERE status = $1 ORDER BY created_at DESC", status
            )
        else:
            rows = await conn.fetch("SELECT id FROM mc_projects ORDER BY created_at DESC")

    projects = []
    for row in rows:
        p = await get_project(row["id"])
        if p:
            projects.append(p)
    return projects


# --- Milestone Execution ---

async def execute_milestone(
    project: Project,
    milestone_id: str,
    on_message=None,
) -> list[ConversationMessage]:
    """
    Execute a single milestone by running a team discussion.

    The conversation engine routes the milestone topic to skill-matched participants.
    Returns the discussion messages.
    """
    milestone = next((m for m in project.milestones if m.id == milestone_id), None)
    if not milestone:
        raise ValueError(f"Milestone {milestone_id} not found")

    # Mark milestone as active
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE mc_milestones SET status = 'active' WHERE id = $1", milestone_id
        )

    # Build discussion topic
    topic = f"""MILESTONE: {milestone.title}
Description: {milestone.description}
Expected deliverable: {milestone.deliverable}

Work on this milestone. Produce the deliverable described above. Be specific and actionable — write actual code, actual plans, actual analysis. Not vague recommendations."""

    project_context = f"Project: {project.name}\nDescription: {project.description}"

    # Load prior conversation history for context
    history_rows = await (await get_pool()).fetch(
        "SELECT * FROM mc_messages WHERE project_id = $1 ORDER BY created_at DESC LIMIT 30",
        project.id,
    )
    history = [
        ConversationMessage(
            id=r["id"],
            project_id=r["project_id"],
            role=MessageRole(r["role"]),
            participant_name=r["participant_name"] or "",
            participant_model=r["participant_model"] or "",
            content=r["content"],
            skill_tags=json.loads(r["skill_tags"]) if r["skill_tags"] else [],
        )
        for r in reversed(history_rows)
    ]

    # Run the discussion
    messages = await run_discussion(
        topic=topic,
        team=project.team,
        project_context=project_context,
        history=history,
        on_message=on_message,
    )

    # Set project_id on all messages and persist
    async with pool.acquire() as conn:
        for msg in messages:
            msg.project_id = project.id
            msg.milestone_id = milestone_id
            await conn.execute(
                """INSERT INTO mc_messages (id, project_id, milestone_id, role, participant_name, participant_model, content, skill_tags)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                msg.id, msg.project_id, msg.milestone_id, msg.role.value,
                msg.participant_name, msg.participant_model, msg.content,
                json.dumps(msg.skill_tags),
            )

    # Compile result from all messages
    result_text = "\n\n".join(
        f"**{m.participant_name}**: {m.content}" for m in messages
    )

    # Mark milestone completed
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE mc_milestones SET status = 'completed', result = $1, completed_at = NOW()
               WHERE id = $2""",
            result_text[:10000], milestone_id,
        )

    return messages


async def advance_project(project_id: str, on_message=None) -> Project:
    """Execute the next pending milestone in a project."""
    project = await get_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")

    next_milestone = next(
        (m for m in project.milestones if m.status == MilestoneStatus.pending),
        None,
    )
    if not next_milestone:
        # All milestones done — mark project completed
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE mc_projects SET status = 'completed', updated_at = NOW() WHERE id = $1",
                project_id,
            )
        return await get_project(project_id)

    # Update project status to active
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE mc_projects SET status = 'active', updated_at = NOW() WHERE id = $1",
            project_id,
        )

    await execute_milestone(project, next_milestone.id, on_message=on_message)
    return await get_project(project_id)


# --- Action Queue ---

async def create_action(
    project_id: str,
    title: str,
    description: str,
    urgency: ActionUrgency = ActionUrgency.normal,
    blocking_milestone: str | None = None,
) -> HumanAction:
    """Create a human action request."""
    action = HumanAction(
        project_id=project_id,
        title=title,
        description=description,
        urgency=urgency,
        blocking_milestone=blocking_milestone,
    )
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO mc_actions (id, project_id, title, description, urgency, blocking_milestone)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            action.id, action.project_id, action.title,
            action.description, action.urgency.value, action.blocking_milestone,
        )
    return action


async def resolve_action(action_id: str) -> None:
    """Mark an action as completed."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE mc_actions SET status = 'completed', resolved_at = NOW() WHERE id = $1",
            action_id,
        )


async def list_actions(project_id: str | None = None, status: str = "pending") -> list[HumanAction]:
    """List action items, optionally filtered by project."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if project_id:
            rows = await conn.fetch(
                "SELECT * FROM mc_actions WHERE project_id = $1 AND status = $2 ORDER BY created_at DESC",
                project_id, status,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM mc_actions WHERE status = $1 ORDER BY created_at DESC", status
            )
    return [
        HumanAction(
            id=r["id"],
            project_id=r["project_id"],
            title=r["title"],
            description=r["description"] or "",
            urgency=ActionUrgency(r["urgency"]),
            status=r["status"],
            blocking_milestone=r["blocking_milestone"],
            created_at=r["created_at"],
            resolved_at=r["resolved_at"],
        )
        for r in rows
    ]


# --- Budget ---

async def fund_project(project_id: str, amount: float) -> None:
    """Add budget to a project."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE mc_projects SET budget_allocated = budget_allocated + $1, updated_at = NOW() WHERE id = $2",
            amount, project_id,
        )
        await conn.execute(
            "INSERT INTO mc_budget_ledger (project_id, amount, description, category) VALUES ($1, $2, $3, $4)",
            project_id, amount, f"Budget allocation: ${amount}", "funding",
        )
```

**Step 2: Verify imports**

```bash
cd /data/ai-mesh && python -c "
import sys; sys.path.insert(0, '.')
from meshcorp.projects import create_project, get_project, list_projects
print('Projects module OK')
"
```

**Step 3: Commit**

```bash
git add meshcorp/projects.py
git commit -m "feat(meshcorp): project lifecycle manager with milestones, actions, budget"
```

---

## Task 6: API Routes

**Files:**
- Modify: `meshcorp/main.py`
- Create: `meshcorp/routes.py`

**Step 1: Create API routes**

Create `meshcorp/routes.py` — all REST and WebSocket endpoints:
```python
"""
MeshCorp HQ API routes.

REST endpoints for project management, template listing, action queue.
WebSocket for real-time conversation streaming.
"""

import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from meshcorp.models import (
    CreateProjectRequest, FundProjectRequest, CEOMessageRequest,
    ConversationMessage, MessageRole, ProjectStatus,
)
from meshcorp.templates import list_templates, get_template
from meshcorp.projects import (
    create_project, get_project, list_projects, advance_project,
    fund_project, list_actions, resolve_action, create_action,
)
from meshcorp.conversation import run_discussion, extract_skill_tags
from meshcorp.db import get_pool

router = APIRouter(prefix="/api")

# Connected WebSocket clients
ws_clients: list[WebSocket] = []


async def broadcast_ws(event: str, data: dict):
    """Send event to all connected WebSocket clients."""
    message = json.dumps({"event": event, "data": data})
    disconnected = []
    for ws in ws_clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        ws_clients.remove(ws)


# --- Templates ---

@router.get("/templates")
async def api_list_templates():
    return {"templates": [t.model_dump() for t in list_templates()]}


@router.get("/templates/{template_id}")
async def api_get_template(template_id: str):
    t = get_template(template_id)
    if not t:
        raise HTTPException(404, f"Template '{template_id}' not found")
    return t.model_dump()


# --- Projects ---

@router.post("/projects")
async def api_create_project(req: CreateProjectRequest, background_tasks: BackgroundTasks):
    """Create a new project. Kicks off AI planning in background."""
    project = await create_project(req.template_id, req.description, req.model)
    await broadcast_ws("project_created", {
        "id": project.id,
        "name": project.name,
        "template_id": project.template_id,
        "status": project.status.value,
    })
    return project.model_dump()


@router.get("/projects")
async def api_list_projects(status: str | None = None):
    projects = await list_projects(status)
    return {"projects": [p.model_dump() for p in projects]}


@router.get("/projects/{project_id}")
async def api_get_project(project_id: str):
    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, f"Project '{project_id}' not found")

    # Also fetch actions and recent messages
    actions = await list_actions(project_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        msg_rows = await conn.fetch(
            "SELECT * FROM mc_messages WHERE project_id = $1 ORDER BY created_at DESC LIMIT 50",
            project_id,
        )

    messages = [
        {
            "id": r["id"],
            "role": r["role"],
            "participant_name": r["participant_name"],
            "participant_model": r["participant_model"],
            "content": r["content"],
            "skill_tags": json.loads(r["skill_tags"]) if r["skill_tags"] else [],
            "milestone_id": r["milestone_id"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in reversed(msg_rows)
    ]

    return {
        "project": project.model_dump(),
        "actions": [a.model_dump() for a in actions],
        "messages": messages,
    }


@router.post("/projects/{project_id}/advance")
async def api_advance_project(project_id: str, background_tasks: BackgroundTasks):
    """Execute the next pending milestone."""
    project = await get_project(project_id)
    if not project:
        raise HTTPException(404, f"Project '{project_id}' not found")

    async def on_message(msg: ConversationMessage):
        await broadcast_ws("message", {
            "project_id": project_id,
            "participant_name": msg.participant_name,
            "content": msg.content,
            "skill_tags": msg.skill_tags,
        })

    async def run_in_background():
        await advance_project(project_id, on_message=on_message)
        updated = await get_project(project_id)
        await broadcast_ws("milestone_completed", {
            "project_id": project_id,
            "status": updated.status.value if updated else "unknown",
        })

    background_tasks.add_task(run_in_background)
    return {"status": "advancing", "project_id": project_id}


@router.post("/projects/{project_id}/fund")
async def api_fund_project(project_id: str, req: FundProjectRequest):
    project = await get_project(project_id)
    if not project:
        raise HTTPException(404)
    await fund_project(project_id, req.amount)
    return {"status": "funded", "amount": req.amount}


@router.post("/projects/{project_id}/kill")
async def api_kill_project(project_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE mc_projects SET status = 'killed', updated_at = NOW() WHERE id = $1",
            project_id,
        )
    return {"status": "killed"}


# --- CEO Chat ---

@router.post("/projects/{project_id}/chat")
async def api_ceo_chat(project_id: str, req: CEOMessageRequest, background_tasks: BackgroundTasks):
    """Send a CEO message into a project's discussion. Team responds."""
    project = await get_project(project_id)
    if not project:
        raise HTTPException(404)

    # Save CEO message
    pool = await get_pool()
    async with pool.acquire() as conn:
        import uuid
        msg_id = str(uuid.uuid4())[:8]
        await conn.execute(
            """INSERT INTO mc_messages (id, project_id, role, participant_name, content, skill_tags)
               VALUES ($1, $2, 'user', 'CEO', $3, $4)""",
            msg_id, project_id, req.content, json.dumps(extract_skill_tags(req.content)),
        )

    await broadcast_ws("message", {
        "project_id": project_id,
        "participant_name": "CEO",
        "content": req.content,
        "role": "user",
    })

    async def on_message(msg: ConversationMessage):
        await broadcast_ws("message", {
            "project_id": project_id,
            "participant_name": msg.participant_name,
            "content": msg.content,
            "skill_tags": msg.skill_tags,
        })

    async def run_discussion_bg():
        # Load history
        rows = await conn.fetch(
            "SELECT * FROM mc_messages WHERE project_id = $1 ORDER BY created_at DESC LIMIT 30",
            project_id,
        )
        history = [
            ConversationMessage(
                id=r["id"], project_id=r["project_id"],
                role=MessageRole(r["role"]),
                participant_name=r["participant_name"] or "",
                participant_model=r["participant_model"] or "",
                content=r["content"],
                skill_tags=json.loads(r["skill_tags"]) if r["skill_tags"] else [],
            )
            for r in reversed(rows)
        ]

        messages = await run_discussion(
            topic=req.content,
            team=project.team,
            project_context=f"Project: {project.name}\n{project.description}",
            history=history,
            on_message=on_message,
        )

        # Persist response messages
        async with pool.acquire() as c:
            for msg in messages:
                msg.project_id = project_id
                await c.execute(
                    """INSERT INTO mc_messages (id, project_id, role, participant_name, participant_model, content, skill_tags)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                    msg.id, msg.project_id, msg.role.value,
                    msg.participant_name, msg.participant_model, msg.content,
                    json.dumps(msg.skill_tags),
                )

    background_tasks.add_task(run_discussion_bg)
    return {"status": "sent"}


# --- Actions ---

@router.get("/actions")
async def api_list_actions(project_id: str | None = None):
    actions = await list_actions(project_id)
    return {"actions": [a.model_dump() for a in actions]}


@router.post("/actions/{action_id}/resolve")
async def api_resolve_action(action_id: str):
    await resolve_action(action_id)
    return {"status": "resolved"}


# --- Dashboard ---

@router.get("/dashboard")
async def api_dashboard():
    """Combined overview: active projects, pending actions, budget."""
    active = await list_projects("active")
    planning = await list_projects("planning")
    proposals = await list_projects("proposal")
    actions = await list_actions()

    total_allocated = sum(p.budget_allocated for p in active + planning)
    total_spent = sum(p.budget_spent for p in active + planning)

    return {
        "active_projects": [p.model_dump() for p in active],
        "planning_projects": [p.model_dump() for p in planning],
        "proposals": [p.model_dump() for p in proposals],
        "pending_actions": [a.model_dump() for a in actions],
        "financials": {
            "total_allocated": float(total_allocated),
            "total_spent": float(total_spent),
        },
    }


# --- WebSocket ---

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")

            if msg_type == "ping":
                await websocket.send_text(json.dumps({"event": "pong"}))

    except WebSocketDisconnect:
        if websocket in ws_clients:
            ws_clients.remove(websocket)
```

**Step 2: Update main.py to include routes**

Replace `meshcorp/main.py` with:
```python
import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from meshcorp.db import init_db
    from meshcorp.templates import load_templates
    await init_db()
    load_templates()
    yield


app = FastAPI(title="MeshCorp HQ", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
from meshcorp.routes import router
app.include_router(router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "meshcorp-hq",
        "uptime": round(time.time() - start_time),
    }


# Serve Svelte frontend
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")

    @app.get("/{path:path}")
    async def serve_frontend(path: str):
        file_path = os.path.join(frontend_dir, path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_dir, "index.html"))
```

**Step 3: Commit**

```bash
git add meshcorp/routes.py meshcorp/main.py
git commit -m "feat(meshcorp): API routes with REST + WebSocket for projects, templates, actions, dashboard"
```

---

## Task 7: Docker Compose Integration

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Add meshcorp-hq service to docker-compose.yml**

Add after the `collab-chat` service block:
```yaml
  # --- MeshCorp HQ (replaces company roundtables + collab-chat) ---

  meshcorp-hq:
    image: python:3.12-slim
    container_name: ai-mesh-meshcorp-hq
    restart: unless-stopped
    ports:
      - "8150:8000"
    environment:
      - ROUTER_URL=http://ai-mesh-router:8000
      - CLAUDE_CODE_URL=http://ai-mesh-claude-code:8000
      - AGENTS_URL=http://ai-mesh-crewai:8000
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - POSTGRES_HOST=${POSTGRES_HOST:-prompt-template-db}
      - POSTGRES_DB=${POSTGRES_DB:-ai_mesh}
      - POSTGRES_USER=${POSTGRES_USER:-admin}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - RESEND_API_KEY=${RESEND_API_KEY}
      - OWNER_EMAIL=${OWNER_EMAIL:-}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID:-}
      - DISCORD_WEBHOOK_URL=${DISCORD_WEBHOOK_URL:-}
      - PUSHOVER_USER_KEY=${PUSHOVER_USER_KEY:-}
      - PUSHOVER_API_TOKEN=${PUSHOVER_API_TOKEN:-}
      - TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID:-}
      - TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN:-}
      - TWILIO_FROM_NUMBER=${TWILIO_FROM_NUMBER:-}
      - OWNER_PHONE=${OWNER_PHONE:-}
    volumes:
      - ./meshcorp:/app
    working_dir: /app
    entrypoint: >
      sh -c "pip install --quiet -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port 8000"
    depends_on:
      ai-router:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - ai-mesh
      - ai-stack
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 5
```

**Step 2: Verify service starts**

```bash
cd /data/ai-mesh && docker compose up -d meshcorp-hq
docker logs ai-mesh-meshcorp-hq -f --tail 30
```

Wait for `Uvicorn running on http://0.0.0.0:8000` then:
```bash
curl -s http://localhost:8150/health | jq
curl -s http://localhost:8150/api/templates | jq '.templates[].name'
```

**Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(meshcorp): add meshcorp-hq service to docker-compose (port 8150)"
```

---

## Task 8: Svelte Frontend — Project Scaffolding

**Files:**
- Create: `meshcorp/frontend/` (Svelte project via `npm create`)

**Step 1: Scaffold Svelte project**

```bash
cd /data/ai-mesh/meshcorp && npx sv create frontend --template minimal --types ts --no-add-ons --no-install
cd /data/ai-mesh/meshcorp/frontend && npm install
```

Note: If `npx sv create` is not available, use:
```bash
cd /data/ai-mesh/meshcorp && npm create vite@latest frontend -- --template svelte-ts
cd /data/ai-mesh/meshcorp/frontend && npm install
```

**Step 2: Configure Vite for API proxy**

Update `meshcorp/frontend/vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/api': 'http://localhost:8150',
      '/ws': {
        target: 'ws://localhost:8150',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
```

**Step 3: Build and verify**

```bash
cd /data/ai-mesh/meshcorp/frontend && npm run build
ls dist/
```

**Step 4: Commit**

```bash
git add meshcorp/frontend/
git commit -m "feat(meshcorp): scaffold Svelte frontend with Vite"
```

---

## Task 9: Svelte Frontend — Dashboard UI

**Files:**
- Modify: `meshcorp/frontend/src/App.svelte`
- Create: `meshcorp/frontend/src/lib/api.ts`
- Create: `meshcorp/frontend/src/lib/websocket.ts`
- Create: `meshcorp/frontend/src/lib/stores.ts`
- Create: `meshcorp/frontend/src/components/Sidebar.svelte`
- Create: `meshcorp/frontend/src/components/ProjectDetail.svelte`
- Create: `meshcorp/frontend/src/components/LiveFeed.svelte`
- Create: `meshcorp/frontend/src/components/NewProject.svelte`
- Create: `meshcorp/frontend/src/components/ActionItem.svelte`

This task creates the full war-room dashboard. Due to the size of the UI, implement this as a complete working dashboard with all panels. The exact Svelte component code will be written during implementation based on Svelte 5 syntax (runes: `$state`, `$derived`, `$effect`).

**Key UI panels:**
1. **Left sidebar** — Project list (active/planning/proposals/completed), inbox/action count
2. **Top center** — Selected project header with milestone progress bar
3. **Middle** — Milestone list with status indicators and deliverables
4. **Bottom** — Live conversation feed with participant messages streaming in
5. **Input bar** — CEO message input at bottom
6. **New project modal** — Template grid picker + description input
7. **Action items** — Slide-out panel for pending human actions

**Styling:** Dark theme using CSS variables. Zinc/neutral palette, monospace for data, sans-serif for UI text.

**Step 1: Create API client, WebSocket manager, and Svelte stores**

These are the data layer that all components share.

**Step 2: Create each component listed above**

Build from outside in: App shell -> Sidebar -> ProjectDetail -> LiveFeed -> NewProject -> ActionItem.

**Step 3: Build and test**

```bash
cd /data/ai-mesh/meshcorp/frontend && npm run build
docker restart ai-mesh-meshcorp-hq
# Open http://192.168.50.23:8150 in browser
```

**Step 4: Commit**

```bash
git add meshcorp/frontend/
git commit -m "feat(meshcorp): war-room dashboard UI with project management, live feed, action queue"
```

---

## Task 10: Integration Test

**Files:**
- Create: `tests/test_meshcorp.py`

**Step 1: Write integration tests**

Create `tests/test_meshcorp.py`:
```python
"""
Integration tests for MeshCorp HQ.
Requires: meshcorp-hq container running at localhost:8150
           ai-router running at localhost:8110
"""
import httpx
import pytest

BASE_URL = "http://localhost:8150"


@pytest.fixture
def client():
    return httpx.Client(base_url=BASE_URL, timeout=30.0)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "meshcorp-hq"


def test_list_templates(client):
    r = client.get("/api/templates")
    assert r.status_code == 200
    templates = r.json()["templates"]
    assert len(templates) >= 7
    names = [t["name"] for t in templates]
    assert "Tech Startup" in names
    assert "Hedge Fund" in names
    assert "Law Firm" in names


def test_get_template(client):
    r = client.get("/api/templates/tech-startup")
    assert r.status_code == 200
    t = r.json()
    assert t["id"] == "tech-startup"
    assert len(t["roles"]) >= 5


def test_template_not_found(client):
    r = client.get("/api/templates/nonexistent")
    assert r.status_code == 404


def test_dashboard(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert "active_projects" in data
    assert "pending_actions" in data
    assert "financials" in data


def test_create_project(client):
    """Create a project using tech-startup template with a description."""
    r = client.post("/api/projects", json={
        "template_id": "tech-startup",
        "description": "Build a simple todo list API with user authentication",
        "model": "deepseek-chat",  # use cheap model for testing
    }, timeout=120.0)
    assert r.status_code == 200
    data = r.json()
    assert data["id"]
    assert data["name"]
    assert data["template_id"] == "tech-startup"
    assert len(data["team"]) >= 5
    assert len(data["milestones"]) >= 3


def test_list_projects(client):
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert "projects" in r.json()


def test_list_actions(client):
    r = client.get("/api/actions")
    assert r.status_code == 200
    assert "actions" in r.json()
```

**Step 2: Run tests**

```bash
cd /data/ai-mesh && pytest tests/test_meshcorp.py -v
```

**Step 3: Commit**

```bash
git add tests/test_meshcorp.py
git commit -m "test(meshcorp): integration tests for health, templates, projects, dashboard"
```

---

## Task 11: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

Add MeshCorp HQ to the architecture docs, port table, and commands section. Add port 8150 and note that it replaces the old company roundtables (8130-8134) and collab-chat (8139).

**Step 1: Update CLAUDE.md with MeshCorp HQ info**

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add MeshCorp HQ to CLAUDE.md"
```

---

## Summary

| Task | Component | Est. Complexity |
|------|-----------|----------------|
| 1 | Backend scaffold | Small |
| 2 | Database schema + models | Medium |
| 3 | Organization templates (7) | Medium |
| 4 | Event-driven conversation engine | Large (core logic) |
| 5 | Project lifecycle manager | Large (core logic) |
| 6 | API routes (REST + WebSocket) | Medium |
| 7 | Docker compose integration | Small |
| 8 | Svelte frontend scaffold | Small |
| 9 | Dashboard UI (all components) | Large (UI) |
| 10 | Integration tests | Small |
| 11 | Update docs | Small |

**After Phase 1 is complete, you will have:**
- A single MeshCorp HQ app at port 8150
- 7 organization templates (tech startup, hedge fund, law firm, marketing agency, research lab, e-commerce, consulting)
- Event-driven conversations where only relevant experts speak
- Milestone-based project execution
- CEO chat to direct teams
- Action queue for human-required items
- War-room dashboard with live conversation streaming
- Budget tracking per project
