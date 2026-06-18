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
import httpx
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
        max_rounds: Max discussion rounds

    Returns:
        List of new ConversationMessage objects from this discussion
    """
    messages: list[ConversationMessage] = []
    all_tags = set(extract_skill_tags(topic))
    responded = set()

    for round_num in range(max_rounds):
        participants = match_participants(
            list(all_tags),
            team,
            include_lead=(round_num > 0),
        )

        # Round 0: everyone matched who hasn't spoken. Round 1+: re-engage if new info
        if round_num == 0:
            to_speak = [p for p in participants if p.role not in responded]
        else:
            to_speak = [p for p in participants if p.role not in responded or round_num > 0]

        if not to_speak:
            break

        new_tags_this_round = set()

        for participant in to_speak:
            # Build message context
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

            # Add the topic or follow-up prompt
            if not messages:
                llm_messages.append({"role": "user", "content": topic})
            elif round_num > 0 and participant.role in responded:
                llm_messages.append({
                    "role": "user",
                    "content": "Based on the discussion above, do you have anything to add or revise? If not, say PASS.",
                })

            response = await call_model(participant.model, llm_messages)

            # Skip if participant passes
            if response.strip().upper() == "PASS":
                continue

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

            # Track new skill tags
            response_tags = set(extract_skill_tags(response))
            new_tags_this_round |= response_tags - all_tags

            if on_message:
                await on_message(msg)

        all_tags |= new_tags_this_round

        # Stop if no new tags introduced after round 1
        if not new_tags_this_round and round_num > 0:
            break

    # Final: lead reviews if they haven't spoken
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
