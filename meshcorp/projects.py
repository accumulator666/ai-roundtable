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
        idea_prompt = (
            f"You are a {template.name} executive. Propose one specific, actionable project idea "
            f"that a {template.name} could execute profitably. Be concrete — name the product/service, "
            f"target customer, and how it makes money. Respond with just the project pitch in 2-3 sentences."
        )
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
        clean = milestones_raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1].rsplit("```", 1)[0]
        milestone_data = json.loads(clean)
    except (json.JSONDecodeError, IndexError):
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
        for m in milestone_data
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
    """Execute a single milestone by running a team discussion."""
    milestone = next((m for m in project.milestones if m.id == milestone_id), None)
    if not milestone:
        raise ValueError(f"Milestone {milestone_id} not found")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE mc_milestones SET status = 'active' WHERE id = $1", milestone_id
        )

    topic = f"""MILESTONE: {milestone.title}
Description: {milestone.description}
Expected deliverable: {milestone.deliverable}

Work on this milestone. Produce the deliverable described above. Be specific and actionable — write actual code, actual plans, actual analysis. Not vague recommendations."""

    project_context = f"Project: {project.name}\nDescription: {project.description}"

    # Load prior conversation history
    async with pool.acquire() as conn:
        history_rows = await conn.fetch(
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

    messages = await run_discussion(
        topic=topic,
        team=project.team,
        project_context=project_context,
        history=history,
        on_message=on_message,
    )

    # Persist messages and mark milestone completed
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

    result_text = "\n\n".join(
        f"**{m.participant_name}**: {m.content}" for m in messages
    )

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
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE mc_projects SET status = 'completed', updated_at = NOW() WHERE id = $1",
                project_id,
            )
        return await get_project(project_id)

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
