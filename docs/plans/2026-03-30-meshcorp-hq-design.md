# MeshCorp HQ — Dynamic AI Organization Platform

**Date:** 2026-03-30
**Status:** Design phase
**Replaces:** All current roundtable UIs (ports 8130-8134, 8139)
**Keeps:** Router (8110), proxies (8100-8105), Redis, PostgreSQL, R730, Claude Code (8104), CrewAI (8120)

---

## Vision

A single unified platform that operates like a Fortune 500 holding company. You spin up any type of organization (tech startup, hedge fund, law firm, marketing agency, research lab — anything) and the system auto-assembles the right AI team from all available resources. Projects run from idea to market with real execution — actual code, real Stripe products, real marketing — not just discussion.

## Design Decisions

### Operating Model
- **Command Center + Autopilot** — Rich dashboard for hands-on work, plus fully autonomous mode where the AI company operates on its own
- **Full spectrum business** — Digital products, content businesses, consulting, affiliate, real-world opportunities
- **AI-driven opportunity discovery** — MeshVentures logic continuously researches trends and proposes new projects
- **Milestone-based pipeline** — No rigid stages. Team proposes milestones per project, each with a deliverable and go/no-go checkpoint

### Budget & Approvals
- **Zero-budget by default** — Companies operate at $0 until you inject funds
- **Manual funding** — You allocate budget to specific projects when you see fit
- **Every spend request comes to you** with justification (what, why, how much)

### Notifications
- **Tiered** — Critical blockers (can't continue without your input) push to phone immediately. Everything else waits in dashboard inbox.
- Push channels: Email, Pushover/Telegram/Discord (TBD)

### AI Conversations
- **Event-driven** — Participants speak only when they have relevant expertise. CTO proposes architecture, only Security and DevOps respond. No wasted turns from irrelevant participants.
- Behind the scenes: topic/skill tagging determines who should respond

### UI
- **Project-centric** — No company/department tabs visible. You see projects, proposals, inbox, and live conversations
- **War room + live feed** — Top: project overview with milestones. Bottom: real-time discussion for selected project
- **Dark theme**, information-dense, Bloomberg-meets-Linear aesthetic
- **Single port**, replaces all 6 current UIs

---

## Core Feature: Dynamic Organizations

### Quick-Start Templates

Instead of hardcoded companies, pick a template that auto-assembles the right team:

```
[Tech Startup] [Hedge Fund] [Law Firm] [Marketing Agency]
[Research Lab] [E-Commerce] [Consulting] [Custom...]
[Auto-Generate — AI picks the opportunity]
```

### Template -> Team Assembly

Each template defines roles. The system maps roles to the best available AI resource.

#### Tech Startup
| Role | Default Model | Reasoning |
|------|--------------|-----------|
| Tech Lead / Code Reviewer | Claude Code | Architecture, PR review, quality gate |
| Frontend Dev | Codex / OpenCode | Fast UI generation |
| Backend Dev | Claude Code | System design, API implementation |
| DevOps / Infra | Grok | Scripting, infrastructure |
| Product Manager | GPT-5.2 | Specs, user stories, prioritization |
| Designer | Gemini | Multimodal, UI mockups |
| QA / Testing | DeepSeek | Cheap, thorough, edge cases |

#### Hedge Fund
| Role | Default Model | Reasoning |
|------|--------------|-----------|
| Portfolio Manager | Claude | Complex multi-factor reasoning |
| Quant Analyst | DeepSeek | Math-heavy, cheap for iteration |
| Risk Manager | GPT-5.2 | Conservative, thorough analysis |
| Market Researcher | Grok | Real-time data, broad research |
| Compliance Officer | Claude | Regulatory nuance |
| Data Engineer | Claude Code | Builds data pipelines |

#### Law Firm
| Role | Default Model | Reasoning |
|------|--------------|-----------|
| Senior Partner | Claude | Nuanced legal reasoning |
| Associate Attorney | GPT-5.2 | Research, drafting briefs |
| Paralegal | DeepSeek | Document review, high volume |
| Legal Researcher | Grok | Broad research capability |
| Contract Specialist | Claude | Detail-oriented drafting |

#### Marketing Agency
| Role | Default Model | Reasoning |
|------|--------------|-----------|
| Creative Director | GPT-5.2 | Campaign strategy, big picture |
| Copywriter | Claude | Persuasive, tone-aware writing |
| SEO Specialist | DeepSeek | Keyword analysis, cheap iteration |
| Social Media Manager | Grok | Trend-aware, real-time |
| Graphic Designer | Gemini | Image generation, multimodal |
| Analytics Lead | DeepSeek | Data crunching, reporting |

#### Custom
User describes what they need in natural language. System analyzes the description, picks roles and models.

### Template System Architecture

Templates stored as JSON:
```json
{
  "id": "tech-startup",
  "name": "Tech Startup",
  "icon": "rocket",
  "description": "Full-stack product team for building software",
  "roles": [
    {
      "title": "Tech Lead",
      "model": "claude-code",
      "persona": "Senior staff engineer. Reviews all code...",
      "skills": ["architecture", "code_review", "technical_decisions"],
      "is_lead": true
    },
    ...
  ],
  "default_milestones": [
    "Validate demand + competitive analysis",
    "Technical design + architecture",
    "MVP implementation",
    "Testing + QA",
    "Launch + marketing push"
  ]
}
```

Templates are starting points — the AI can suggest adding/removing roles based on the specific project.

---

## Project Lifecycle

### 1. Initiation
- **Manual:** You pick a template, describe the project, AI assembles team and proposes milestones
- **Auto-generate:** System runs continuous market research, proposes opportunities with business case

### 2. Planning
- Assembled team discusses approach (event-driven — only relevant experts speak)
- AI proposes milestones with deliverables and estimated resource needs
- System identifies what it needs from you: API keys, accounts, domain, budget
- **You approve the plan and fund it** (or revise, or kill)

### 3. Execution
- Each milestone executes with real work:
  - **Code:** Claude Code / Codex / OpenCode write actual code in repos
  - **Content:** AI generates marketing copy, landing pages, emails
  - **Finance:** Models build financial models, analyze markets
  - **Legal:** AI drafts contracts, reviews compliance
  - **Infrastructure:** n8n workflows, Docker deployments, CI/CD setup
- Tech Lead (or role lead) reviews all output, requests rewrites if needed
- Progress visible in real-time on dashboard

### 4. Checkpoints
- At each milestone completion, you get a status report
- Go / No-go / Redirect decision
- Budget request for next phase if needed

### 5. Launch & Operate
- System handles deployment, marketing push, monitoring
- Ongoing: tracks revenue, user metrics, issues
- Reports back with performance data

### 6. Human Action Requests
When the system can't proceed without you, it queues a request:
```
[URGENT] Need Stripe account for payment processing
  Project: AI Invoice SaaS
  What: Sign up at stripe.com, provide API keys
  Why: Can't implement checkout without it
  Blocking: Milestone 3 (MVP implementation)
  [Mark Complete] [Provide Keys] [Skip This]
```

---

## Event-Driven Conversation Engine

### How It Works
1. A topic/message enters the discussion
2. System analyzes the content and extracts skill tags (e.g., "JWT auth" -> `security`, `backend`, `architecture`)
3. Only participants whose skills match the tags are invited to respond
4. Participants respond in sequence (not parallel) so each sees prior responses
5. If a response introduces new skill tags, new participants may be pulled in
6. Conversation continues until:
   - Consensus reached (participants agree on approach)
   - Lead/reviewer approves the decision
   - You intervene with a directive

### Skill Matching
Each participant has skills (from template). Messages are tagged by the system:
- "We need a database schema" -> `backend`, `data_engineering`
- "What's the legal risk?" -> `legal`, `compliance`
- "How do we price this?" -> `finance`, `pricing`, `market_research`
- "The CI pipeline is failing" -> `devops`, `qa`

### Your Participation
You can always jump in. When you type a message:
- If directed ("@Backend Dev fix the auth bug") -> routes to that participant
- If general ("I want to pivot to B2B") -> all relevant participants respond
- Your messages override AI decisions (you're the CEO)

---

## Dashboard UI Spec

### Layout
```
+----------------------------------------------------------+
|  MeshCorp HQ              [Autopilot ON]  [$0]  [!3]     |
+------------+---------------------------------------------+
|            |                                              |
| PROJECTS   |  PROJECT: AI Invoice SaaS                   |
|  Active(3) |  Template: Tech Startup                     |
|  > Invoice |  Status: Building MVP   [Milestone 2/5]     |
|    Course  |  Budget: $0 spent / $0 allocated             |
|    API Svc |  Team: 6 active participants                 |
|            |                                              |
|  Proposals |  MILESTONES          DELIVERABLES            |
|    (2 new) |  done Validate       Market research doc     |
|            |  >>> Build MVP       repo: invoice-saas      |
|  Completed |      Launch beta     --                      |
|    (1)     |      Marketing       --                      |
|            |      Scale           --                      |
| INBOX [!3] |                                              |
|            +----------------------------------------------+
|  ! Need    |  LIVE DISCUSSION                             |
|    Stripe  |                                              |
|  ! Approve |  >>> Building auth system                    |
|    $12     |  [Backend Dev] Proposing JWT + refresh       |
|    domain  |  tokens. Here's the schema...                |
|  ! Review  |  [Security] Needs rate limiting on the       |
|    proposal|  token endpoint. Redis-backed approach...    |
|            |  [DevOps] I'll wire up CI once auth is       |
|            |  merged. GitHub Actions + Docker.            |
|            |                                              |
|            |  > Direct the team...                        |
+------------+----------------------------------------------+
```

### New Project Flow
```
+--NEW PROJECT-------------------------------------------+
|                                                         |
|  [Tech Startup] [Hedge Fund] [Law Firm] [Agency]       |
|  [Research Lab] [E-Commerce] [Consulting] [Custom...]   |
|  [Auto-Generate]                                        |
|                                                         |
|  Selected: Tech Startup                                 |
|                                                         |
|  Describe your idea (or leave blank for auto):          |
|  [Build an AI-powered invoicing tool that___________]   |
|                                                         |
|  [Launch Project]                                       |
+--------------------------------------------------------+
```

### Dark theme, design principles:
- Information-dense but not cluttered
- Monospace for data/metrics (Geist Mono), sans-serif for UI text
- Zinc/neutral palette, one accent color for active states
- No unnecessary animations or gradients

---

## Available AI Resources

### Cloud APIs (via AI Mesh Router)
| Provider | Models | Best For |
|----------|--------|----------|
| Anthropic (Claude) | claude-opus-4-6, claude-sonnet-4-5, claude-haiku-4-5 | Complex reasoning, writing, legal, code review |
| OpenAI | gpt-5.2, gpt-5-mini, o3, o3-mini | Product thinking, specs, general purpose |
| xAI (Grok) | grok-3, grok-3-mini | Real-time research, scripting |
| Google (Gemini) | gemini-2.0-flash | Multimodal, image analysis, UI mockups |
| DeepSeek | deepseek-chat, deepseek-reasoner | Math, data analysis, cheap high-volume work |

### Coding Agents
| Tool | Access Method | Best For |
|------|-------------|----------|
| Claude Code | REST API (8104) | Architecture, complex code, review |
| Codex (OpenAI) | API | Fast code generation, UI |
| OpenCode | CLI/API | Alternative code generation |
| Microsoft Copilot | API | Code completion, boilerplate |

### Local AI (R730 — 192.168.50.179)
| Model | VRAM | Best For |
|-------|------|----------|
| deepseek-coder:33b | 24GB | Code generation (free) |
| deepseek-r1:32b | 24GB | Reasoning (free) |
| qwen2.5:32b | 24GB | General purpose (free) |
| dolphin-mixtral | 24GB | Uncensored/creative (free) |
| + 6 more smaller models | | Paralegal-type grunt work |

### Execution Tools
| Tool | What It Does |
|------|-------------|
| CrewAI Agents (8120) | Multi-step background job execution |
| n8n (5678) | Workflow automation, API integrations |
| Stripe API | Payment processing, product creation |
| Cloudflare API | Domain registration, DNS |
| Resend API | Email sending |
| GitHub API | Repo creation, CI/CD |

---

## Technical Architecture

### What Changes
| Component | Current | New |
|-----------|---------|-----|
| UI | 6 separate apps (8130-8134, 8139) | 1 unified dashboard (single port) |
| Company system | 5 hardcoded companies | Dynamic template-based team assembly |
| Conversation engine | Parallel fire-all + synthesis | Event-driven, skill-matched, sequential |
| Project pipeline | Rigid pitch->execute | Milestone-based, adaptive per project |
| Execution | Discussion only | Real code, real deployments, real transactions |
| Autonomy | Manual-only | Autopilot + manual modes |

### What Stays
| Component | Why |
|-----------|-----|
| AI Router (8110) | Works well, model routing is solid |
| All proxies (8100-8105) | API normalization layer is clean |
| Claude Code API (8104) | Real code execution |
| CrewAI Agents (8120) | Background job execution |
| Redis | Pub/sub, state, caching |
| PostgreSQL (ai_mesh) | Persistent state |
| R730 + local Ollama | Free inference capacity |
| n8n | Workflow automation |

### New Components Needed
1. **MeshCorp HQ Backend** — New FastAPI app replacing all company backends. Handles: template engine, team assembly, event-driven conversation, project lifecycle, budget tracking, notification system, autopilot loop
2. **MeshCorp HQ Frontend** — Svelte SPA dashboard. WebSocket for live updates. Dark theme, project-centric layout.
3. **Template Registry** — JSON files defining organization templates + role-to-model mappings
4. **Notification Service** — Multi-channel: Email (Resend), Telegram bot, Discord, Pushover, SMS (Twilio). Urgency-based routing configurable per channel.
5. **Execution Engine** — Orchestrates real work: calls Claude Code for coding (multiple instances for parallel projects), n8n for workflows, external APIs for purchases
6. **Autopilot Daemon** — Background process: market research loop, opportunity scoring, proposal generation

### Database Schema Updates (ai_mesh)
New/updated tables:
- `organizations` — Active orgs (template used, status, team composition)
- `projects` — Milestone-based projects with budget tracking (replaces current)
- `milestones` — Per-project milestones with deliverables and status
- `conversations` — Event-driven discussion threads per project
- `messages` — Individual messages with skill tags, participant, content
- `action_queue` — Human action requests (need API key, approve spend, etc.)
- `budget_ledger` — All financial transactions per project (keep existing, extend)
- `notifications` — Outbound notification log
- `templates` — Organization templates (can be user-customized)
- `autopilot_proposals` — AI-generated project proposals awaiting approval

---

## Implementation Phases

### Phase 1: Foundation
- New backend app with template engine and team assembly
- New dashboard UI with project-centric layout
- Event-driven conversation engine (replaces parallel-fire-all)
- Basic project lifecycle (create -> milestones -> execute manually)
- Migrate off old company roundtables

### Phase 2: Real Execution
- Claude Code integration for actual coding tasks
- n8n integration for workflow automation
- External API execution (Stripe, Cloudflare, GitHub)
- Tech Lead code review loop (review -> approve/reject -> rewrite)
- File/artifact tracking per project

### Phase 3: Autonomy
- Autopilot daemon (market research loop)
- Proposal generation and approval flow
- Notification system (push to phone for critical items)
- Budget request/approval workflow
- Auto-generate project mode

### Phase 4: Polish
- Custom template creation UI
- Project analytics and P&L reporting
- Historical performance tracking
- Template effectiveness scoring (which teams produce best results)

---

## Resolved Decisions
- **Frontend:** Svelte SPA — reactive, compiles to lean JS, perfect for real-time WebSocket dashboard
- **Notifications:** All channels — Email (Resend), Telegram bot, Discord, Pushover, SMS (Twilio). Configurable urgency routing.
- **Parallel coding:** Multiple Claude Code container instances — each project gets its own container/workspace for true parallel execution
- **First template:** Tech Startup (recommended for testing — exercises code execution, review loop, and deployment)

## Open Questions
- Domain for external access, or localhost-only for now?
- Twilio account for SMS — set up now or defer to Phase 3?
- Telegram bot token — create now or defer?
- Discord server/webhook — existing or new?
