"""
Project Orchestrator — Fortune 500 workflow engine.

CEO pitches an idea → AI creates outline → tasks assigned to specialists
across all companies → parallel execution → results combined.

Usage from holding/main.py:
    from shared.orchestrator import ProjectOrchestrator
    orch = ProjectOrchestrator(router_url, company_urls)
    project = await orch.pitch_to_project("Build a SaaS for X")
    await orch.execute(project["id"])
    await orch.integrate(project["id"])
"""

import os
import json
import asyncio
import logging
import time
from typing import Any, Optional
from uuid import uuid4

import httpx

logger = logging.getLogger("orchestrator")

ROUTER_URL = os.environ.get("ROUTER_URL", "http://ai-mesh-router:8000")

# Where each company lives (container names on the ai-mesh network)
COMPANY_URLS = {
    "holding": os.environ.get("HOLDING_URL", "http://ai-mesh-holding-board:8000"),
    "meshtech": os.environ.get("MESHTECH_URL", "http://ai-mesh-meshtech:8000"),
    "meshmedia": os.environ.get("MESHMEDIA_URL", "http://ai-mesh-meshmedia:8000"),
    "meshcapital": os.environ.get("MESHCAPITAL_URL", "http://ai-mesh-meshcapital:8000"),
    "meshventures": os.environ.get("MESHVENTURES_URL", "http://ai-mesh-meshventures:8000"),
}

# ============================================================
# Skill → Company/Role routing
# ============================================================

SKILL_ROUTING: dict[str, dict[str, Any]] = {
    # MeshTech — software engineering
    "frontend": {"company": "meshtech", "participants": ["Frontend Dev", "Full-Stack Dev"]},
    "backend": {"company": "meshtech", "participants": ["Backend Dev", "Full-Stack Dev"]},
    "fullstack": {"company": "meshtech", "participants": ["Full-Stack Dev", "Tech Lead"]},
    "architecture": {"company": "meshtech", "participants": ["CTO", "Tech Lead", "Database Architect"]},
    "database": {"company": "meshtech", "participants": ["Database Architect", "Backend Dev"]},
    "security": {"company": "meshtech", "participants": ["Security Engineer"]},
    "devops": {"company": "meshtech", "participants": ["DevOps"]},
    "ai_engineering": {"company": "meshtech", "participants": ["AI Engineer"]},
    "qa_testing": {"company": "meshtech", "participants": ["QA Engineer"]},
    "product_management": {"company": "meshtech", "participants": ["Product Manager", "CTO"]},
    "coding": {"company": "meshtech", "participants": ["Full-Stack Dev", "Backend Dev", "Frontend Dev"]},

    # MeshMedia — content and marketing
    "marketing": {"company": "meshmedia", "participants": ["Creative Director", "Social Media Manager"]},
    "content_creation": {"company": "meshmedia", "participants": ["Copywriter", "Content Producer"]},
    "seo": {"company": "meshmedia", "participants": ["SEO Specialist", "Social Media Manager"]},
    "branding": {"company": "meshmedia", "participants": ["Creative Director", "Copywriter"]},
    "social_media": {"company": "meshmedia", "participants": ["Social Media Manager", "Influencer Manager"]},
    "copywriting": {"company": "meshmedia", "participants": ["Copywriter"]},

    # MeshCapital — finance and analysis
    "finance": {"company": "meshcapital", "participants": ["Wealth Optimizer", "Accountant"]},
    "risk_analysis": {"company": "meshcapital", "participants": ["Risk Manager", "Data Analyst"]},
    "data_analysis": {"company": "meshcapital", "participants": ["Data Analyst", "Quant Analyst"]},
    "pricing": {"company": "meshcapital", "participants": ["Wealth Optimizer", "Data Analyst"]},
    "accounting": {"company": "meshcapital", "participants": ["Accountant"]},
    "financial_modeling": {"company": "meshcapital", "participants": ["Data Analyst", "Quant Analyst"]},

    # MeshVentures — research, sales, new business
    "market_research": {"company": "meshventures", "participants": ["Market Researcher", "Competitive Intel"]},
    "sales": {"company": "meshventures", "participants": ["Sales Director"]},
    "ideation": {"company": "meshventures", "participants": ["Brainstormer", "Devil's Advocate"]},
    "competitive_analysis": {"company": "meshventures", "participants": ["Competitive Intel", "Market Researcher"]},
    "ecommerce": {"company": "meshventures", "participants": ["E-commerce Ops"]},
    "go_to_market": {"company": "meshventures", "participants": ["Sales Director", "Market Researcher"]},
    "customer_research": {"company": "meshventures", "participants": ["Market Researcher"]},

    # Holding — strategy, legal, governance
    "strategy": {"company": "holding", "participants": ["CEO", "Chief of Staff"]},
    "legal": {"company": "holding", "participants": ["Business Attorney", "Tax Attorney"]},
    "governance": {"company": "holding", "participants": ["COO", "Corporate Secretary"]},
    "tax": {"company": "holding", "participants": ["Tax Attorney", "CFO"]},
    "executive_review": {"company": "holding", "participants": ["CEO", "CFO", "COO"]},
}

# All valid skill tags for the AI to choose from
VALID_SKILLS = sorted(SKILL_ROUTING.keys())

# ============================================================
# Prompt templates
# ============================================================

OUTLINE_PROMPT = """You are a Fortune 500 Chief of Staff. The CEO just pitched this idea:

---
{pitch}
---

Create a structured project outline. Respond ONLY with valid JSON (no markdown fences). Use this exact structure:

{{
  "project_name": "short name",
  "summary": "1-2 sentence summary",
  "target_customer": "who buys this",
  "revenue_model": "how it makes money",
  "phases": [
    {{
      "name": "Phase 1: Discovery",
      "description": "what happens in this phase",
      "tasks": [
        {{
          "title": "short task title",
          "description": "what needs to be done (2-3 sentences, specific and actionable)",
          "skill": "one of: {skills}",
          "priority": "high/medium/low"
        }}
      ]
    }}
  ]
}}

Rules:
- 3-5 phases (Discovery → Design → Build → Launch → Optimize)
- 2-5 tasks per phase
- Each task.skill MUST be exactly one of the valid skills listed above
- Tasks should be specific enough that one specialist can complete them independently
- Include tasks for: market research, architecture, coding (frontend+backend+security), marketing, finance/pricing, sales strategy
- Think about what a real Fortune 500 company would delegate to each department"""

INTEGRATION_PROMPT = """You are a Fortune 500 Chief of Staff running the integration meeting. The team worked independently on their assigned tasks for the project: "{project_name}"

Original pitch: {pitch}

Here are the completed results from each team member:

{results_text}

Now synthesize everything into ONE cohesive deliverable:
1. What was built/researched (combine all technical + business work)
2. Key findings and decisions
3. Gaps or conflicts between team outputs (and how to resolve them)
4. Recommended next steps (prioritized)
5. Overall project status and readiness score (1-10)

Be specific. Reference each team member's work by name."""


class ProjectOrchestrator:
    """Manages the full lifecycle: pitch → outline → assign → execute → integrate."""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        # In-memory project store (also persisted to DB when available)
        self.projects: dict[str, dict] = {}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=120.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ----------------------------------------------------------
    # Step 1: Pitch → Structured Outline
    # ----------------------------------------------------------

    async def pitch_to_project(self, pitch: str, model: str = "gpt-5.2") -> dict:
        """CEO pitches an idea. AI generates a structured project outline."""
        project_id = uuid4().hex[:12]

        prompt = OUTLINE_PROMPT.format(pitch=pitch, skills=", ".join(VALID_SKILLS))

        client = self._get_client()
        try:
            resp = await client.post(
                f"{ROUTER_URL}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a project planning AI. Respond ONLY with valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.4,
                },
                timeout=120.0,
            )
            if resp.status_code != 200:
                raise Exception(f"Router returned {resp.status_code}")

            raw = resp.json()["choices"][0]["message"]["content"]
            # Strip markdown fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            outline = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse outline JSON: {e}\nRaw: {raw[:500]}")
            outline = {
                "project_name": "Parse Error",
                "summary": f"AI output couldn't be parsed. Raw start: {raw[:200]}",
                "phases": [],
            }
        except Exception as e:
            logger.error(f"Failed to generate outline: {e}")
            outline = {
                "project_name": "Error",
                "summary": str(e),
                "phases": [],
            }

        # Build task list with assignments
        tasks = []
        for phase in outline.get("phases", []):
            for task_def in phase.get("tasks", []):
                skill = task_def.get("skill", "strategy")
                if skill not in SKILL_ROUTING:
                    skill = self._fuzzy_match_skill(skill)

                routing = SKILL_ROUTING.get(skill, SKILL_ROUTING["strategy"])
                task_id = uuid4().hex[:8]
                tasks.append({
                    "id": task_id,
                    "title": task_def.get("title", "Untitled"),
                    "description": task_def.get("description", ""),
                    "skill": skill,
                    "priority": task_def.get("priority", "medium"),
                    "phase": phase.get("name", ""),
                    "assigned_company": routing["company"],
                    "assigned_participants": routing["participants"],
                    "status": "pending",
                    "result": None,
                })

        project = {
            "id": project_id,
            "pitch": pitch,
            "outline": outline,
            "tasks": tasks,
            "status": "planned",  # planned → executing → integrating → completed
            "created_at": time.time(),
            "results": {},
        }

        self.projects[project_id] = project

        # Persist to DB if available
        try:
            from shared.db import save_project
            await save_project(project)
        except Exception as e:
            logger.warning(f"Could not persist project to DB: {e}")

        return project

    def _fuzzy_match_skill(self, skill: str) -> str:
        """Try to match an invalid skill tag to the closest valid one."""
        skill_lower = skill.lower().replace(" ", "_").replace("-", "_")
        # Direct match
        if skill_lower in SKILL_ROUTING:
            return skill_lower
        # Substring match
        for valid in SKILL_ROUTING:
            if valid in skill_lower or skill_lower in valid:
                return valid
        # Keyword mapping
        keyword_map = {
            "code": "coding", "program": "coding", "develop": "coding",
            "ui": "frontend", "ux": "frontend", "react": "frontend", "css": "frontend",
            "api": "backend", "server": "backend", "endpoint": "backend",
            "test": "qa_testing", "quality": "qa_testing",
            "deploy": "devops", "docker": "devops", "ci": "devops",
            "design": "architecture", "schema": "database",
            "market": "market_research", "research": "market_research",
            "sell": "sales", "revenue": "pricing", "price": "pricing",
            "brand": "branding", "content": "content_creation",
            "social": "social_media", "seo": "seo",
            "money": "finance", "budget": "finance", "cost": "finance",
            "risk": "risk_analysis", "legal": "legal", "law": "legal",
            "customer": "customer_research", "user": "customer_research",
            "launch": "go_to_market", "gtm": "go_to_market",
            "ai": "ai_engineering", "ml": "ai_engineering", "model": "ai_engineering",
            "secure": "security", "auth": "security", "encrypt": "security",
        }
        for keyword, mapped_skill in keyword_map.items():
            if keyword in skill_lower:
                return mapped_skill
        return "strategy"  # fallback

    # ----------------------------------------------------------
    # Step 2: Execute tasks in parallel across companies
    # ----------------------------------------------------------

    async def execute(self, project_id: str, on_progress: Optional[Any] = None) -> dict:
        """Send tasks to the right companies for parallel execution."""
        project = self.projects.get(project_id)
        if not project:
            return {"error": "Project not found"}

        project["status"] = "executing"
        tasks = project["tasks"]

        # Group tasks by company
        by_company: dict[str, list[dict]] = {}
        for task in tasks:
            company = task["assigned_company"]
            by_company.setdefault(company, []).append(task)

        logger.info(f"Executing project {project_id}: {len(tasks)} tasks across {len(by_company)} companies")

        # Execute all tasks in parallel (grouped by company)
        async def execute_company_tasks(company: str, company_tasks: list[dict]):
            url = COMPANY_URLS.get(company)
            if not url:
                logger.error(f"No URL for company {company}")
                for t in company_tasks:
                    t["status"] = "error"
                    t["result"] = f"No URL configured for company: {company}"
                return

            client = self._get_client()
            # Execute tasks for this company sequentially (each is a roundtable discussion)
            for task in company_tasks:
                task["status"] = "in_progress"
                if on_progress:
                    await on_progress({
                        "type": "task_started",
                        "task_id": task["id"],
                        "title": task["title"],
                        "company": company,
                        "participants": task["assigned_participants"],
                    })

                try:
                    resp = await client.post(
                        f"{url}/api/execute-task",
                        json={
                            "task_id": task["id"],
                            "title": task["title"],
                            "description": task["description"],
                            "skill": task["skill"],
                            "participants": task["assigned_participants"],
                            "project_context": project["outline"].get("summary", ""),
                        },
                        timeout=180.0,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        task["status"] = "completed"
                        task["result"] = data.get("result", "No result returned")
                    else:
                        task["status"] = "error"
                        task["result"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
                except Exception as e:
                    task["status"] = "error"
                    task["result"] = f"Error: {str(e)[:200]}"

                if on_progress:
                    await on_progress({
                        "type": "task_completed" if task["status"] == "completed" else "task_error",
                        "task_id": task["id"],
                        "title": task["title"],
                        "company": company,
                        "status": task["status"],
                    })

        # Run all companies in parallel
        await asyncio.gather(*[
            execute_company_tasks(company, company_tasks)
            for company, company_tasks in by_company.items()
        ])

        project["status"] = "executed"

        # Persist
        try:
            from shared.db import update_project_status
            await update_project_status(project_id, "executed", tasks)
        except Exception:
            pass

        return project

    # ----------------------------------------------------------
    # Step 3: Integration — combine all results
    # ----------------------------------------------------------

    async def integrate(self, project_id: str, model: str = "gpt-5.2") -> dict:
        """Reconvene the team: combine all task results into a final deliverable."""
        project = self.projects.get(project_id)
        if not project:
            return {"error": "Project not found"}

        project["status"] = "integrating"

        # Build results text
        completed = [t for t in project["tasks"] if t["status"] == "completed"]
        if not completed:
            return {"error": "No completed tasks to integrate"}

        results_parts = []
        for task in completed:
            results_parts.append(
                f"### {task['title']} (by {', '.join(task['assigned_participants'])} @ {task['assigned_company']})\n"
                f"Skill: {task['skill']} | Priority: {task['priority']}\n\n"
                f"{task['result']}\n"
            )
        results_text = "\n---\n".join(results_parts)

        prompt = INTEGRATION_PROMPT.format(
            project_name=project["outline"].get("project_name", "Unknown"),
            pitch=project["pitch"],
            results_text=results_text,
        )

        client = self._get_client()
        try:
            resp = await client.post(
                f"{ROUTER_URL}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a Fortune 500 Chief of Staff synthesizing team deliverables."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.5,
                },
                timeout=180.0,
            )
            if resp.status_code != 200:
                raise Exception(f"Router returned {resp.status_code}")

            synthesis = resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            synthesis = f"Integration failed: {str(e)}"

        project["synthesis"] = synthesis
        project["status"] = "completed"

        # Persist
        try:
            from shared.db import update_project_status
            await update_project_status(project_id, "completed", project["tasks"], synthesis)
        except Exception:
            pass

        return project

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def get_project(self, project_id: str) -> Optional[dict]:
        return self.projects.get(project_id)

    def list_projects(self) -> list[dict]:
        return [
            {
                "id": p["id"],
                "name": p["outline"].get("project_name", "Unknown"),
                "status": p["status"],
                "task_count": len(p["tasks"]),
                "completed": sum(1 for t in p["tasks"] if t["status"] == "completed"),
                "created_at": p["created_at"],
            }
            for p in self.projects.values()
        ]

    def get_task_summary(self, project_id: str) -> dict:
        project = self.projects.get(project_id)
        if not project:
            return {"error": "not found"}
        by_company: dict[str, list] = {}
        for task in project["tasks"]:
            c = task["assigned_company"]
            by_company.setdefault(c, []).append({
                "id": task["id"],
                "title": task["title"],
                "skill": task["skill"],
                "participants": task["assigned_participants"],
                "status": task["status"],
                "priority": task["priority"],
            })
        return {
            "project_id": project_id,
            "status": project["status"],
            "by_company": by_company,
            "total": len(project["tasks"]),
            "completed": sum(1 for t in project["tasks"] if t["status"] == "completed"),
            "errors": sum(1 for t in project["tasks"] if t["status"] == "error"),
        }
