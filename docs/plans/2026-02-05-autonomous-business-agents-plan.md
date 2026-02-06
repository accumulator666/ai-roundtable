# Autonomous Business Agents — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a CrewAI-based autonomous business agent system with 5 specialized agents, Stripe payments, email marketing, domain purchasing, and automated revenue reinvestment — all running on the existing ai-mesh Docker infrastructure.

**Architecture:** CrewAI container with 5 agents (Strategist, Researcher, Builder, Marketer, Finance) calling AI models through the ai-mesh router. Langflow for reusable pipelines. n8n for external integrations, scheduling, and notifications. PostgreSQL for shared state and audit trail.

**Tech Stack:** Python 3.12, CrewAI, FastAPI, Stripe API, Resend, Cloudflare API, PostgreSQL, Redis

---

### Task 1: Database schema for business agents

**Files:**
- Create: `/data/ai-mesh/agents/init_db.sql`

**Step 1: Create the SQL schema**

Create `/data/ai-mesh/agents/init_db.sql`:

```sql
-- Run against existing ai_mesh database
-- docker exec -i prompt-template-db psql -U admin -d ai_mesh < agents/init_db.sql

CREATE TABLE IF NOT EXISTS businesses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'planning',
    business_type TEXT,
    stripe_product_id TEXT,
    domain TEXT,
    deploy_url TEXT,
    total_revenue NUMERIC(12,2) DEFAULT 0,
    total_cost NUMERIC(12,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID REFERENCES businesses(id),
    agent TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    description TEXT NOT NULL,
    reasoning TEXT,
    outcome TEXT,
    cost NUMERIC(10,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS budget_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID REFERENCES businesses(id),
    transaction_type TEXT NOT NULL,
    amount NUMERIC(10,2) NOT NULL,
    description TEXT,
    agent TEXT,
    stripe_transaction_id TEXT,
    approved_by TEXT DEFAULT 'auto',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID REFERENCES businesses(id),
    agent TEXT NOT NULL,
    task_type TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    input_data JSONB DEFAULT '{}',
    output_data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shared_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT UNIQUE NOT NULL,
    value JSONB NOT NULL,
    agent TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_businesses_status ON businesses(status);
CREATE INDEX IF NOT EXISTS idx_decisions_business ON decisions(business_id);
CREATE INDEX IF NOT EXISTS idx_ledger_business ON budget_ledger(business_id);
CREATE INDEX IF NOT EXISTS idx_ledger_type ON budget_ledger(transaction_type);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON agent_tasks(agent);
CREATE INDEX IF NOT EXISTS idx_memory_key ON shared_memory(key);
```

**Step 2: Run against database**

```bash
docker exec -i prompt-template-db psql -U admin -d ai_mesh < /data/ai-mesh/agents/init_db.sql
```

**Step 3: Verify**

```bash
docker exec prompt-template-db psql -U admin -d ai_mesh -c "\dt"
```

Expected: `businesses`, `decisions`, `budget_ledger`, `agent_tasks`, `shared_memory` plus existing tables.

**Step 4: Commit**

```bash
cd /data/ai-mesh && git add agents/init_db.sql && git commit -m "feat: add business agent database schema"
```

---

### Task 2: Agent tools — budget and memory

**Files:**
- Create: `/data/ai-mesh/agents/tools/__init__.py`
- Create: `/data/ai-mesh/agents/tools/budget_tools.py`
- Create: `/data/ai-mesh/agents/tools/memory_tools.py`

**Step 1: Create tools package**

Create `/data/ai-mesh/agents/tools/__init__.py`:

```python
```

**Step 2: Create budget tools**

Create `/data/ai-mesh/agents/tools/budget_tools.py`:

```python
import os
import httpx
from crewai.tools import tool

POSTGRES_CONN = f"postgresql://{os.environ.get('POSTGRES_USER', 'admin')}:{os.environ.get('POSTGRES_PASSWORD', '')}@{os.environ.get('POSTGRES_HOST', 'prompt-template-db')}:5432/{os.environ.get('POSTGRES_DB', 'ai_mesh')}"

LIMIT_PER_ACTION = float(os.environ.get("SPENDING_LIMIT_PER_ACTION", 20))
LIMIT_DAILY = float(os.environ.get("SPENDING_LIMIT_DAILY", 100))
REINVEST_PERCENT = float(os.environ.get("REVENUE_REINVEST_PERCENT", 10))


@tool("check_budget")
def check_budget() -> str:
    """Check current budget status including autonomous pool, daily spending, and limits."""
    import asyncpg, asyncio

    async def _check():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            daily_spent = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'expense' AND created_at >= CURRENT_DATE"
            )
            total_revenue = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'revenue'"
            )
            total_expenses = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'expense'"
            )
            autonomous_pool = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'reinvestment'"
            )
            pool_spent = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'expense' AND approved_by = 'auto'"
            )
            available_pool = float(autonomous_pool) - float(pool_spent)
            return (
                f"Daily spent: ${daily_spent:.2f} / ${LIMIT_DAILY:.2f}\n"
                f"Per-action limit: ${LIMIT_PER_ACTION:.2f}\n"
                f"Total revenue: ${total_revenue:.2f}\n"
                f"Total expenses: ${total_expenses:.2f}\n"
                f"Net profit: ${float(total_revenue) - float(total_expenses):.2f}\n"
                f"Autonomous pool: ${available_pool:.2f}\n"
                f"Reinvest rate: {REINVEST_PERCENT}%"
            )
        finally:
            await conn.close()

    return asyncio.get_event_loop().run_until_complete(_check())


@tool("record_expense")
def record_expense(amount: float, description: str, agent: str, business_id: str = None) -> str:
    """Record an expense. Returns 'approved' if under limits, 'blocked' if over."""
    import asyncpg, asyncio

    if amount > LIMIT_PER_ACTION:
        return f"BLOCKED: ${amount:.2f} exceeds per-action limit of ${LIMIT_PER_ACTION:.2f}. Needs human approval."

    async def _record():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            daily_spent = await conn.fetchval(
                "SELECT COALESCE(SUM(amount), 0) FROM budget_ledger WHERE transaction_type = 'expense' AND created_at >= CURRENT_DATE"
            )
            if float(daily_spent) + amount > LIMIT_DAILY:
                return f"BLOCKED: Daily limit would be exceeded. Spent today: ${daily_spent:.2f}, limit: ${LIMIT_DAILY:.2f}"

            await conn.execute(
                "INSERT INTO budget_ledger (business_id, transaction_type, amount, description, agent, approved_by) VALUES ($1, 'expense', $2, $3, $4, 'auto')",
                business_id, amount, description, agent
            )
            return f"APPROVED: ${amount:.2f} recorded for {description}"
        finally:
            await conn.close()

    return asyncio.get_event_loop().run_until_complete(_record())


@tool("record_revenue")
def record_revenue(amount: float, description: str, business_id: str, stripe_transaction_id: str = None) -> str:
    """Record revenue from a payment."""
    import asyncpg, asyncio

    async def _record():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            await conn.execute(
                "INSERT INTO budget_ledger (business_id, transaction_type, amount, description, agent, stripe_transaction_id) VALUES ($1, 'revenue', $2, $3, 'finance', $4)",
                business_id, amount, description, stripe_transaction_id
            )
            await conn.execute(
                "UPDATE businesses SET total_revenue = total_revenue + $1 WHERE id = $2::uuid",
                amount, business_id
            )
            return f"Revenue recorded: ${amount:.2f} for {description}"
        finally:
            await conn.close()

    return asyncio.get_event_loop().run_until_complete(_record())
```

**Step 3: Create shared memory tools**

Create `/data/ai-mesh/agents/tools/memory_tools.py`:

```python
import os
import json
from crewai.tools import tool

POSTGRES_CONN = f"postgresql://{os.environ.get('POSTGRES_USER', 'admin')}:{os.environ.get('POSTGRES_PASSWORD', '')}@{os.environ.get('POSTGRES_HOST', 'prompt-template-db')}:5432/{os.environ.get('POSTGRES_DB', 'ai_mesh')}"


@tool("save_memory")
def save_memory(key: str, value: str, agent: str) -> str:
    """Save a value to shared memory that all agents can access. Use for decisions, plans, context."""
    import asyncpg, asyncio

    async def _save():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            await conn.execute(
                """INSERT INTO shared_memory (key, value, agent, updated_at)
                   VALUES ($1, $2::jsonb, $3, NOW())
                   ON CONFLICT (key) DO UPDATE SET value = $2::jsonb, agent = $3, updated_at = NOW()""",
                key, json.dumps({"data": value}), agent
            )
            return f"Saved to shared memory: {key}"
        finally:
            await conn.close()

    return asyncio.get_event_loop().run_until_complete(_save())


@tool("read_memory")
def read_memory(key: str) -> str:
    """Read a value from shared memory."""
    import asyncpg, asyncio

    async def _read():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            row = await conn.fetchrow("SELECT value, agent, updated_at FROM shared_memory WHERE key = $1", key)
            if row:
                val = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                return f"Key: {key}\nValue: {val.get('data', val)}\nSet by: {row['agent']}\nUpdated: {row['updated_at']}"
            return f"No memory found for key: {key}"
        finally:
            await conn.close()

    return asyncio.get_event_loop().run_until_complete(_read())


@tool("list_memories")
def list_memories() -> str:
    """List all keys in shared memory."""
    import asyncpg, asyncio

    async def _list():
        conn = await asyncpg.connect(POSTGRES_CONN)
        try:
            rows = await conn.fetch("SELECT key, agent, updated_at FROM shared_memory ORDER BY updated_at DESC LIMIT 50")
            if not rows:
                return "Shared memory is empty."
            lines = [f"  {r['key']} (by {r['agent']}, {r['updated_at']})" for r in rows]
            return "Shared memory keys:\n" + "\n".join(lines)
        finally:
            await conn.close()

    return asyncio.get_event_loop().run_until_complete(_list())
```

**Step 4: Commit**

```bash
cd /data/ai-mesh && git add agents/tools/ && git commit -m "feat: add budget and shared memory tools for agents"
```

---

### Task 3: Agent tools — Stripe, email, domains

**Files:**
- Create: `/data/ai-mesh/agents/tools/stripe_tools.py`
- Create: `/data/ai-mesh/agents/tools/email_tools.py`
- Create: `/data/ai-mesh/agents/tools/domain_tools.py`

**Step 1: Create Stripe tools**

Create `/data/ai-mesh/agents/tools/stripe_tools.py`:

```python
import os
import httpx
from crewai.tools import tool

STRIPE_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_URL = "https://api.stripe.com/v1"


def _stripe_headers():
    return {"Authorization": f"Bearer {STRIPE_KEY}"}


@tool("create_stripe_product")
def create_stripe_product(name: str, description: str, price_cents: int, currency: str = "usd", recurring: str = None) -> str:
    """Create a Stripe product with a price. Set recurring to 'month' or 'year' for subscriptions."""
    with httpx.Client() as client:
        product = client.post(f"{STRIPE_URL}/products", headers=_stripe_headers(), data={
            "name": name, "description": description
        }).json()

        if "error" in product:
            return f"Error creating product: {product['error']['message']}"

        price_data = {
            "product": product["id"],
            "unit_amount": price_cents,
            "currency": currency,
        }
        if recurring:
            price_data["recurring[interval]"] = recurring

        price = client.post(f"{STRIPE_URL}/prices", headers=_stripe_headers(), data=price_data).json()

        if "error" in price:
            return f"Product created ({product['id']}) but price failed: {price['error']['message']}"

        link = client.post(f"{STRIPE_URL}/payment_links", headers=_stripe_headers(), data={
            "line_items[0][price]": price["id"],
            "line_items[0][quantity]": 1,
        }).json()

        payment_url = link.get("url", "N/A")
        return f"Product: {product['id']}\nPrice: {price['id']}\nPayment link: {payment_url}"


@tool("get_stripe_balance")
def get_stripe_balance() -> str:
    """Get current Stripe account balance."""
    with httpx.Client() as client:
        balance = client.get(f"{STRIPE_URL}/balance", headers=_stripe_headers()).json()
        if "error" in balance:
            return f"Error: {balance['error']['message']}"
        available = sum(b["amount"] for b in balance.get("available", []))
        pending = sum(b["amount"] for b in balance.get("pending", []))
        return f"Available: ${available/100:.2f}\nPending: ${pending/100:.2f}"


@tool("list_recent_payments")
def list_recent_payments(limit: int = 10) -> str:
    """List recent successful payments."""
    with httpx.Client() as client:
        charges = client.get(f"{STRIPE_URL}/charges", headers=_stripe_headers(), params={
            "limit": limit, "status": "succeeded"
        }).json()
        if "error" in charges:
            return f"Error: {charges['error']['message']}"
        lines = []
        for c in charges.get("data", []):
            lines.append(f"  ${c['amount']/100:.2f} - {c.get('description', 'N/A')} ({c['created']})")
        return f"Recent payments ({len(lines)}):\n" + "\n".join(lines) if lines else "No recent payments."
```

**Step 2: Create email tools**

Create `/data/ai-mesh/agents/tools/email_tools.py`:

```python
import os
import httpx
from crewai.tools import tool

RESEND_KEY = os.environ.get("RESEND_API_KEY", "")


@tool("send_email")
def send_email(to: str, subject: str, html_body: str, from_email: str = "onboarding@resend.dev") -> str:
    """Send an email via Resend. Use from_email with your verified domain, or onboarding@resend.dev for testing."""
    with httpx.Client() as client:
        resp = client.post("https://api.resend.com/emails", headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
        }, json={
            "from": from_email,
            "to": [to],
            "subject": subject,
            "html": html_body,
        })
        data = resp.json()
        if "id" in data:
            return f"Email sent successfully. ID: {data['id']}"
        return f"Email failed: {data}"


@tool("send_notification")
def send_notification(subject: str, message: str) -> str:
    """Send a notification email to the system owner."""
    owner_email = os.environ.get("OWNER_EMAIL", "")
    if not owner_email:
        return "OWNER_EMAIL not configured. Cannot send notification."
    return send_email.run(to=owner_email, subject=f"[AI Mesh] {subject}", html_body=f"<p>{message}</p>")
```

**Step 3: Create domain tools**

Create `/data/ai-mesh/agents/tools/domain_tools.py`:

```python
import os
import httpx
from crewai.tools import tool

CF_KEY = os.environ.get("CLOUDFLARE_API_KEY", "")
CF_ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CF_URL = "https://api.cloudflare.com/client/v4"


def _cf_headers():
    return {"Authorization": f"Bearer {CF_KEY}", "Content-Type": "application/json"}


@tool("check_domain_available")
def check_domain_available(domain: str) -> str:
    """Check if a domain is available for registration via Cloudflare."""
    with httpx.Client() as client:
        resp = client.get(
            f"{CF_URL}/accounts/{CF_ACCOUNT}/registrar/domains/{domain}",
            headers=_cf_headers()
        )
        data = resp.json()
        if not data.get("success"):
            return f"Domain {domain} appears available (not in your account)."
        info = data.get("result", {})
        return f"Domain {domain}: status={info.get('status', 'unknown')}, expires={info.get('expires_at', 'N/A')}"


@tool("register_domain")
def register_domain(domain: str) -> str:
    """Register a domain via Cloudflare Registrar."""
    with httpx.Client() as client:
        resp = client.post(
            f"{CF_URL}/accounts/{CF_ACCOUNT}/registrar/domains/{domain}/register",
            headers=_cf_headers(),
            json={"auto_renew": True}
        )
        data = resp.json()
        if data.get("success"):
            return f"Domain {domain} registered successfully!"
        errors = data.get("errors", [])
        return f"Registration failed: {errors}"


@tool("setup_dns")
def setup_dns(domain: str, record_type: str, name: str, content: str) -> str:
    """Set up a DNS record for a domain. record_type: A, CNAME, etc."""
    with httpx.Client() as client:
        # First get zone ID
        zones = client.get(f"{CF_URL}/zones", headers=_cf_headers(), params={"name": domain}).json()
        zone_results = zones.get("result", [])
        if not zone_results:
            return f"Zone not found for {domain}. Register the domain first."
        zone_id = zone_results[0]["id"]

        resp = client.post(f"{CF_URL}/zones/{zone_id}/dns_records", headers=_cf_headers(), json={
            "type": record_type, "name": name, "content": content, "proxied": True
        })
        data = resp.json()
        if data.get("success"):
            return f"DNS record created: {record_type} {name} -> {content}"
        return f"DNS setup failed: {data.get('errors', [])}"
```

**Step 4: Commit**

```bash
cd /data/ai-mesh && git add agents/tools/ && git commit -m "feat: add Stripe, email, and domain tools for agents"
```

---

### Task 4: Agent tools — search and builder

**Files:**
- Create: `/data/ai-mesh/agents/tools/search_tools.py`
- Create: `/data/ai-mesh/agents/tools/builder_tools.py`

**Step 1: Create search tools**

Create `/data/ai-mesh/agents/tools/search_tools.py`:

```python
import httpx
from crewai.tools import tool


@tool("web_search")
def web_search(query: str, num_results: int = 10) -> str:
    """Search the web using SearXNG. Returns titles, URLs, and snippets."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.get("http://gluetun:8080/search", params={
            "q": query, "format": "json", "categories": "general", "pageno": 1
        })
        if resp.status_code != 200:
            return f"Search failed: HTTP {resp.status_code}"
        data = resp.json()
        results = data.get("results", [])[:num_results]
        if not results:
            return "No results found."
        lines = []
        for r in results:
            lines.append(f"  [{r.get('title', 'N/A')}]({r.get('url', '')})\n    {r.get('content', '')[:200]}")
        return f"Search results for '{query}':\n" + "\n\n".join(lines)


@tool("ai_research")
def ai_research(topic: str) -> str:
    """Ask the Grok AI researcher to analyze a topic in depth."""
    with httpx.Client(timeout=120.0) as client:
        resp = client.post("http://ai-mesh-router:8000/v1/chat/completions", json={
            "model": "grok-3",
            "messages": [
                {"role": "system", "content": "You are a business researcher. Provide detailed, actionable market analysis with data points, competitor info, and opportunity assessment."},
                {"role": "user", "content": f"Research this business opportunity in depth: {topic}"}
            ],
            "max_tokens": 4096
        })
        if resp.status_code != 200:
            return f"Research failed: {resp.text}"
        return resp.json()["choices"][0]["message"]["content"]
```

**Step 2: Create builder tools**

Create `/data/ai-mesh/agents/tools/builder_tools.py`:

```python
import httpx
from crewai.tools import tool


@tool("build_code")
def build_code(prompt: str) -> str:
    """Send a coding task to Claude Code. It can create files, write code, and build projects."""
    with httpx.Client(timeout=300.0) as client:
        resp = client.post("http://claude-code:8000/v1/code/execute", json={
            "prompt": prompt,
            "working_dir": "/workspace"
        })
        if resp.status_code != 200:
            return f"Build failed: {resp.text}"
        data = resp.json()
        return f"Build completed:\n{data.get('output', 'No output')}"


@tool("deploy_to_cloudflare")
def deploy_to_cloudflare(project_name: str, directory: str = "/workspace/build") -> str:
    """Deploy a static site to Cloudflare Pages."""
    import os
    cf_key = os.environ.get("CLOUDFLARE_API_KEY", "")
    cf_account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")

    with httpx.Client(timeout=120.0) as client:
        # Create project if it doesn't exist
        resp = client.post(
            f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/pages/projects",
            headers={"Authorization": f"Bearer {cf_key}", "Content-Type": "application/json"},
            json={"name": project_name, "production_branch": "main"}
        )
        data = resp.json()
        subdomain = f"{project_name}.pages.dev"
        return f"Cloudflare Pages project created: {subdomain}\nDeploy files to it via Wrangler CLI or API upload."


@tool("ai_generate_content")
def ai_generate_content(prompt: str, style: str = "professional") -> str:
    """Generate marketing content using GPT-4o."""
    with httpx.Client(timeout=120.0) as client:
        resp = client.post("http://ai-mesh-router:8000/v1/chat/completions", json={
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": f"You are an expert copywriter. Write in a {style} style. Be concise, persuasive, and conversion-focused."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 4096
        })
        if resp.status_code != 200:
            return f"Content generation failed: {resp.text}"
        return resp.json()["choices"][0]["message"]["content"]
```

**Step 5: Commit**

```bash
cd /data/ai-mesh && git add agents/tools/ && git commit -m "feat: add search and builder tools for agents"
```

---

### Task 5: CrewAI agent definitions and crew

**Files:**
- Create: `/data/ai-mesh/agents/config/agents.yaml`
- Create: `/data/ai-mesh/agents/config/tasks.yaml`
- Create: `/data/ai-mesh/agents/crew.py`

**Step 1: Create agent config**

Create `/data/ai-mesh/agents/config/agents.yaml`:

```yaml
strategist:
  role: "Chief Strategist"
  goal: "Find profitable business opportunities and coordinate the team to build, launch, and scale them. Maximize revenue with minimal spend."
  backstory: >
    You are the CEO of an AI-powered venture studio. You identify market opportunities,
    create business plans, and delegate execution to your team. You think in terms of
    ROI, market size, speed to revenue, and automation potential. You prefer businesses
    that can be fully automated: digital products, SaaS, content sites, API services.
    You always check the budget before approving spending.
  llm_model: "claude-opus-4-6"

researcher:
  role: "Market Researcher"
  goal: "Provide accurate, data-driven market research, competitor analysis, and trend identification to inform business decisions."
  backstory: >
    You are a meticulous researcher who validates business ideas with real data.
    You search the web, analyze competitors, identify market gaps, and estimate
    demand. You present findings with specific numbers, links, and actionable insights.
    You flag risks honestly — you'd rather kill a bad idea early than waste money.
  llm_model: "grok-3"

builder:
  role: "Technical Builder"
  goal: "Build MVPs, deploy websites, create landing pages, and set up technical infrastructure quickly and reliably."
  backstory: >
    You are a full-stack developer who ships fast. You build MVPs in hours, not weeks.
    You use modern tech (Next.js, Tailwind, Stripe integration) and deploy to
    Cloudflare Pages or Vercel. You write clean, production-ready code and always
    include payment integration, analytics, and SEO basics.
  llm_model: "claude-code"

marketer:
  role: "Growth Marketer"
  goal: "Create compelling content, landing pages, email sequences, and marketing campaigns that drive traffic and conversions."
  backstory: >
    You are a conversion-focused marketer. You write headlines that grab attention,
    copy that sells, and email sequences that nurture leads. You understand SEO,
    content marketing, and direct response. You always include clear CTAs and
    optimize for the target audience.
  llm_model: "gpt-4o"

finance:
  role: "Finance Manager"
  goal: "Track all spending and revenue, manage Stripe products and pricing, enforce budget limits, and maximize profitability."
  backstory: >
    You are the CFO who watches every dollar. You set up Stripe products, create
    payment links, track revenue, and calculate P&L. You enforce spending limits
    strictly — nothing over $20 without human approval. You calculate the 10%
    revenue reinvestment pool nightly and report daily summaries. You are cautious
    and always check the budget before approving any expense.
  llm_model: "claude-sonnet-4-5"
```

**Step 2: Create task templates**

Create `/data/ai-mesh/agents/config/tasks.yaml`:

```yaml
strategy_session:
  description: >
    Review current businesses, their performance, and the remaining budget.
    If no businesses exist yet, research and propose 3 new business ideas.
    For each idea, estimate: startup cost, time to first revenue, monthly revenue potential, automation level.
    Pick the best one and create a detailed execution plan.
    Save your decision and plan to shared memory.
  expected_output: "A business plan with clear next steps for the team."
  agent: strategist

market_research:
  description: >
    Research the business opportunity: {topic}.
    Analyze: market size, existing competitors (with URLs and pricing), target customer profile,
    potential revenue models, and key risks.
    Be specific with numbers and data points.
  expected_output: "A detailed market research report with data, competitors, and recommendation."
  agent: researcher

build_mvp:
  description: >
    Build an MVP for: {business_description}.
    Requirements: Landing page with clear value prop, Stripe payment integration,
    email capture, mobile responsive, fast loading.
    Deploy to Cloudflare Pages and return the live URL.
  expected_output: "A deployed MVP with live URL and Stripe payment link."
  agent: builder

create_marketing:
  description: >
    Create marketing materials for: {business_description}.
    Produce: 1 landing page copy, 3 blog post outlines, 5 social media posts,
    and a 3-email welcome sequence.
    Target audience: {target_audience}.
    Tone: {tone}.
  expected_output: "Complete marketing package ready to publish."
  agent: marketer

financial_setup:
  description: >
    Set up financials for: {business_description}.
    Create Stripe product with appropriate pricing.
    Record the startup costs in the budget ledger.
    Calculate break-even point.
    Report current budget status.
  expected_output: "Stripe product created, costs recorded, break-even analysis complete."
  agent: finance
```

**Step 3: Create crew orchestration**

Create `/data/ai-mesh/agents/crew.py`:

```python
import os
import yaml
from crewai import Agent, Task, Crew, Process, LLM

from tools.budget_tools import check_budget, record_expense, record_revenue
from tools.memory_tools import save_memory, read_memory, list_memories
from tools.stripe_tools import create_stripe_product, get_stripe_balance, list_recent_payments
from tools.email_tools import send_email, send_notification
from tools.domain_tools import check_domain_available, register_domain, setup_dns
from tools.search_tools import web_search, ai_research
from tools.builder_tools import build_code, deploy_to_cloudflare, ai_generate_content

ROUTER_URL = "http://ai-mesh-router:8000/v1"


def make_llm(model: str) -> LLM:
    """Create an LLM that routes through ai-mesh router."""
    return LLM(
        model=f"openai/{model}",
        base_url=ROUTER_URL,
        api_key="not-needed",
    )


def load_config(filename: str) -> dict:
    config_dir = os.path.join(os.path.dirname(__file__), "config")
    with open(os.path.join(config_dir, filename)) as f:
        return yaml.safe_load(f)


def create_agents() -> dict:
    agent_configs = load_config("agents.yaml")

    shared_tools = [check_budget, save_memory, read_memory, list_memories, send_notification]

    agents = {
        "strategist": Agent(
            role=agent_configs["strategist"]["role"],
            goal=agent_configs["strategist"]["goal"],
            backstory=agent_configs["strategist"]["backstory"],
            llm=make_llm(agent_configs["strategist"]["llm_model"]),
            tools=shared_tools + [web_search, ai_research],
            verbose=True,
            allow_delegation=True,
        ),
        "researcher": Agent(
            role=agent_configs["researcher"]["role"],
            goal=agent_configs["researcher"]["goal"],
            backstory=agent_configs["researcher"]["backstory"],
            llm=make_llm(agent_configs["researcher"]["llm_model"]),
            tools=shared_tools + [web_search, ai_research],
            verbose=True,
        ),
        "builder": Agent(
            role=agent_configs["builder"]["role"],
            goal=agent_configs["builder"]["goal"],
            backstory=agent_configs["builder"]["backstory"],
            llm=make_llm(agent_configs["builder"]["llm_model"]),
            tools=shared_tools + [build_code, deploy_to_cloudflare, record_expense],
            verbose=True,
        ),
        "marketer": Agent(
            role=agent_configs["marketer"]["role"],
            goal=agent_configs["marketer"]["goal"],
            backstory=agent_configs["marketer"]["backstory"],
            llm=make_llm(agent_configs["marketer"]["llm_model"]),
            tools=shared_tools + [ai_generate_content, send_email, record_expense],
            verbose=True,
        ),
        "finance": Agent(
            role=agent_configs["finance"]["role"],
            goal=agent_configs["finance"]["goal"],
            backstory=agent_configs["finance"]["backstory"],
            llm=make_llm(agent_configs["finance"]["llm_model"]),
            tools=shared_tools + [
                create_stripe_product, get_stripe_balance, list_recent_payments,
                record_expense, record_revenue,
            ],
            verbose=True,
        ),
    }
    return agents


def run_strategy_session() -> str:
    """Run a full strategy session — the main entry point."""
    agents = create_agents()
    task_configs = load_config("tasks.yaml")

    strategy_task = Task(
        description=task_configs["strategy_session"]["description"],
        expected_output=task_configs["strategy_session"]["expected_output"],
        agent=agents["strategist"],
    )

    crew = Crew(
        agents=list(agents.values()),
        tasks=[strategy_task],
        process=Process.hierarchical,
        manager_agent=agents["strategist"],
        verbose=True,
    )

    result = crew.kickoff()
    return str(result)


def run_business_build(business_description: str, target_audience: str = "general") -> str:
    """Run a full business build cycle."""
    agents = create_agents()
    task_configs = load_config("tasks.yaml")

    research_task = Task(
        description=task_configs["market_research"]["description"].format(topic=business_description),
        expected_output=task_configs["market_research"]["expected_output"],
        agent=agents["researcher"],
    )

    build_task = Task(
        description=task_configs["build_mvp"]["description"].format(business_description=business_description),
        expected_output=task_configs["build_mvp"]["expected_output"],
        agent=agents["builder"],
        context=[research_task],
    )

    marketing_task = Task(
        description=task_configs["create_marketing"]["description"].format(
            business_description=business_description,
            target_audience=target_audience,
            tone="professional and persuasive",
        ),
        expected_output=task_configs["create_marketing"]["expected_output"],
        agent=agents["marketer"],
        context=[research_task],
    )

    finance_task = Task(
        description=task_configs["financial_setup"]["description"].format(business_description=business_description),
        expected_output=task_configs["financial_setup"]["expected_output"],
        agent=agents["finance"],
        context=[research_task, build_task],
    )

    crew = Crew(
        agents=list(agents.values()),
        tasks=[research_task, build_task, marketing_task, finance_task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()
    return str(result)
```

**Step 4: Commit**

```bash
cd /data/ai-mesh && git add agents/config/ agents/crew.py && git commit -m "feat: add CrewAI agent definitions and crew orchestration"
```

---

### Task 6: CrewAI FastAPI app and Dockerfile

**Files:**
- Create: `/data/ai-mesh/agents/main.py`
- Create: `/data/ai-mesh/agents/requirements.txt`
- Create: `/data/ai-mesh/agents/Dockerfile`

**Step 1: Create FastAPI app**

Create `/data/ai-mesh/agents/main.py`:

```python
import asyncio
import time
import uuid
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="AI Business Agents", version="1.0.0")

# In-memory job tracking
jobs: dict = {}


class StrategyRequest(BaseModel):
    pass


class BuildRequest(BaseModel):
    business_description: str
    target_audience: Optional[str] = "general"


class JobStatus(BaseModel):
    job_id: str
    status: str
    result: Optional[str] = None
    started_at: float
    completed_at: Optional[float] = None


def run_in_background(job_id: str, func, *args):
    try:
        jobs[job_id]["status"] = "running"
        result = func(*args)
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result
        jobs[job_id]["completed_at"] = time.time()
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["result"] = str(e)
        jobs[job_id]["completed_at"] = time.time()


@app.post("/v1/agents/strategy-session")
async def strategy_session(background_tasks: BackgroundTasks):
    """Trigger a strategy session. Returns job ID to poll for results."""
    from crew import run_strategy_session

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "queued", "result": None, "started_at": time.time(), "completed_at": None}
    background_tasks.add_task(run_in_background, job_id, run_strategy_session)
    return {"job_id": job_id, "status": "queued", "poll": f"/v1/agents/jobs/{job_id}"}


@app.post("/v1/agents/build-business")
async def build_business(request: BuildRequest, background_tasks: BackgroundTasks):
    """Trigger a full business build cycle. Returns job ID to poll for results."""
    from crew import run_business_build

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "queued", "result": None, "started_at": time.time(), "completed_at": None}
    background_tasks.add_task(run_in_background, job_id, run_business_build, request.business_description, request.target_audience)
    return {"job_id": job_id, "status": "queued", "poll": f"/v1/agents/jobs/{job_id}"}


@app.get("/v1/agents/jobs/{job_id}")
async def get_job(job_id: str):
    """Check status of a running agent job."""
    if job_id not in jobs:
        return {"error": "Job not found"}
    return {"job_id": job_id, **jobs[job_id]}


@app.get("/v1/agents/jobs")
async def list_jobs():
    """List all agent jobs."""
    return {"jobs": [{"job_id": k, **v} for k, v in jobs.items()]}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "crewai-agents", "active_jobs": sum(1 for j in jobs.values() if j["status"] == "running")}
```

**Step 2: Create requirements**

Create `/data/ai-mesh/agents/requirements.txt`:

```
fastapi==0.115.12
uvicorn==0.34.1
crewai[tools]>=0.100.0
httpx==0.28.1
asyncpg==0.30.0
pyyaml==6.0.2
pydantic==2.11.3
```

**Step 3: Create Dockerfile**

Create `/data/ai-mesh/agents/Dockerfile`:

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Step 4: Commit**

```bash
cd /data/ai-mesh && git add agents/main.py agents/requirements.txt agents/Dockerfile && git commit -m "feat: add CrewAI FastAPI service with Dockerfile"
```

---

### Task 7: Add CrewAI to Docker Compose

**Files:**
- Modify: `/data/ai-mesh/docker-compose.yml`

**Step 1: Add crewai-agents service**

Add after the n8n service in docker-compose.yml:

```yaml
  # --- Business Agents ---

  crewai-agents:
    build: ./agents
    container_name: ai-mesh-crewai
    restart: unless-stopped
    ports:
      - "8120:8000"
    environment:
      - POSTGRES_HOST=${POSTGRES_HOST:-prompt-template-db}
      - POSTGRES_DB=${POSTGRES_DB:-ai_mesh}
      - POSTGRES_USER=${POSTGRES_USER:-admin}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY}
      - RESEND_API_KEY=${RESEND_API_KEY}
      - CLOUDFLARE_API_KEY=${CLOUDFLARE_API_KEY}
      - CLOUDFLARE_ACCOUNT_ID=${CLOUDFLARE_ACCOUNT_ID}
      - SPENDING_LIMIT_PER_ACTION=${SPENDING_LIMIT_PER_ACTION:-20}
      - SPENDING_LIMIT_DAILY=${SPENDING_LIMIT_DAILY:-100}
      - SPENDING_LIMIT_MONTHLY=${SPENDING_LIMIT_MONTHLY:-500}
      - REVENUE_REINVEST_PERCENT=${REVENUE_REINVEST_PERCENT:-10}
      - OWNER_EMAIL=${OWNER_EMAIL:-}
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
      retries: 3
```

**Step 2: Build and start**

```bash
cd /data/ai-mesh && docker compose build crewai-agents && docker compose up -d crewai-agents
```

**Step 3: Verify**

```bash
curl http://localhost:8120/health
```

Expected: `{"status":"ok","service":"crewai-agents","active_jobs":0}`

**Step 4: Commit**

```bash
cd /data/ai-mesh && git add docker-compose.yml && git commit -m "feat: add CrewAI agent container to compose"
```

---

### Task 8: n8n scheduled workflows

**Files:**
- Create: `/data/ai-mesh/n8n/daily-strategy-session.json`
- Create: `/data/ai-mesh/n8n/stripe-webhook-handler.json`
- Create: `/data/ai-mesh/n8n/nightly-reinvestment.json`

**Step 1: Create daily strategy session workflow**

Triggers CrewAI Strategist at 9am daily.

**Step 2: Create Stripe webhook handler**

Listens for payment events, calls Finance agent to record revenue.

**Step 3: Create nightly reinvestment workflow**

At midnight, calculates 10% of net revenue, adds to autonomous pool.

**Step 4: Import workflows**

```bash
docker cp /data/ai-mesh/n8n/daily-strategy-session.json ai-mesh-n8n:/tmp/ && \
docker exec ai-mesh-n8n n8n import:workflow --input=/tmp/daily-strategy-session.json
```

**Step 5: Commit**

```bash
cd /data/ai-mesh && git add n8n/ && git commit -m "feat: add n8n scheduled business workflows"
```

---

### Task 9: Add shell shortcuts for agents

**Files:**
- Modify: `/data/ai-mesh/ai-shortcuts.sh`

**Step 1: Add agent shortcuts**

```bash
# Agent commands
ai-strategy()  { curl -s -X POST http://localhost:8120/v1/agents/strategy-session | jq; }
ai-build()     { curl -s -X POST http://localhost:8120/v1/agents/build-business -H "Content-Type: application/json" -d "{\"business_description\": \"$*\"}" | jq; }
ai-jobs()      { curl -s http://localhost:8120/v1/agents/jobs | jq; }
ai-job()       { curl -s http://localhost:8120/v1/agents/jobs/$1 | jq; }
```

**Step 2: Update MOTD with agent shortcuts**

**Step 3: Commit**

```bash
cd /data/ai-mesh && git add ai-shortcuts.sh motd/ && git commit -m "feat: add agent shell shortcuts and update MOTD"
```

---

### Task 10: Test the full system

**Step 1: Initialize agent database tables**

```bash
docker exec -i prompt-template-db psql -U admin -d ai_mesh < /data/ai-mesh/agents/init_db.sql
```

**Step 2: Run a test strategy session**

```bash
source /data/ai-mesh/ai-shortcuts.sh
ai-strategy
```

**Step 3: Check job status**

```bash
ai-jobs
ai-job <job_id>
```

**Step 4: Verify budget tracking**

```bash
source /data/ai-mesh/ai-shortcuts.sh
ai-health
```

---

## Execution Order

Tasks 1-4: Sequential (schema → tools build on each other)
Tasks 5-6: Sequential (crew needs tools)
Task 7: Needs Task 6 (compose needs Dockerfile)
Task 8: Can run in parallel with Task 7
Task 9: After Task 7
Task 10: After everything
