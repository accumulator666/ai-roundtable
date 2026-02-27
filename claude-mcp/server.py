#!/usr/bin/env python3
"""
AI Mesh MCP Server — Gives Claude Code CLI access to the entire AI mesh.

Delegates research, code generation, code review, analysis, and summarization
to cheaper/free models so Claude Code (Opus) saves tokens for orchestration.

Cost tiers:
  FREE  — Local Ollama models (qwen2.5-coder:7b, deepseek-coder:33b, dolphin-llama3:8b, etc.)
  CHEAP — grok-3-mini
  $$    — claude-sonnet-4-5, gpt-4o (only when quality demands it)
"""

import os
import json
import asyncio
from typing import Optional
import httpx
from mcp.server.fastmcp import FastMCP

# --- Config ---
ROUTER_URL = os.environ.get("AI_MESH_ROUTER", "http://localhost:8110")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
TIMEOUT = 120  # seconds per model call

# Model routing table — cheapest capable model for each task type
ROUTING = {
    "code":      "qwen2.5-coder:7b",       # FREE — great at code
    "code_heavy": "deepseek-coder:33b",     # FREE — complex code tasks
    "research":  "grok-3-mini",             # CHEAP — good reasoning + web knowledge
    "analysis":  "qwen2.5:latest",          # FREE — solid general analysis
    "creative":  "dolphin-mistral:latest",  # FREE — uncensored creative
    "general":   "nous-hermes2:latest",     # FREE — good all-rounder
    "reasoning": "grok-3-mini",             # CHEAP — strong reasoning
    "fast":      "dolphin-llama3:8b",       # FREE — fastest local
    "vision":    "gpt-4o",                  # $$ — vision/multimodal tasks
}

# All available models
MODELS = {
    # Local (FREE)
    "qwen2.5-coder:7b": {"cost": "free", "good_at": "code generation, code review, debugging"},
    "deepseek-coder:33b": {"cost": "free", "good_at": "complex code, architecture, algorithms"},
    "qwen2.5:latest": {"cost": "free", "good_at": "analysis, math, structured data"},
    "dolphin-llama3:8b": {"cost": "free", "good_at": "fast responses, general chat, brainstorming"},
    "dolphin-mistral:latest": {"cost": "free", "good_at": "creative writing, uncensored, marketing copy"},
    "nous-hermes2:latest": {"cost": "free", "good_at": "instruction following, general tasks"},
    "wizardlm-uncensored:13b": {"cost": "free", "good_at": "uncensored analysis, edge cases"},
    # Cloud (costs money)
    "grok-3-mini": {"cost": "cheap", "good_at": "research, reasoning, current events, math"},
    "deepseek-chat": {"cost": "cheap", "good_at": "code, reasoning, analysis (check balance)"},
    "gpt-4o": {"cost": "moderate", "good_at": "broad knowledge, vision, function calling"},
    "gpt-4o-mini": {"cost": "cheap", "good_at": "fast cloud model, good at structured output"},
    "claude-sonnet-4-5": {"cost": "expensive", "good_at": "complex reasoning, nuanced writing, planning"},
}

mcp = FastMCP(
    "AI Mesh",
    instructions="Access the AI mesh — delegate tasks to cheaper/free models to save tokens",
)


async def _call_model(model: str, prompt: str, system: str = "", max_tokens: int = 4096) -> str:
    """Call a model through the AI mesh router."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.post(
                f"{ROUTER_URL}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            return f"[Error: {model} timed out after {TIMEOUT}s]"
        except Exception as e:
            return f"[Error calling {model}: {str(e)}]"


async def _call_multiple(models: list[str], prompt: str, system: str = "") -> dict[str, str]:
    """Call multiple models in parallel, return {model: response}."""
    tasks = {m: _call_model(m, prompt, system) for m in models}
    results = {}
    for model, coro in tasks.items():
        results[model] = await coro
    return results


# ===================================================================
# TOOLS — Claude Code can call these to delegate work
# ===================================================================

@mcp.tool()
async def delegate_research(
    query: str,
    context: str = "",
    model: str = "",
) -> str:
    """Delegate a research question to a cheaper model. Use this for fact-finding,
    market research, competitor analysis, technology comparisons, or any information
    gathering that doesn't require Opus-level reasoning.

    Args:
        query: The research question or topic to investigate.
        context: Optional additional context to help the model.
        model: Specific model to use (default: auto-routes to grok-3-mini).
    """
    target = model or ROUTING["research"]
    system = "You are a thorough researcher. Provide specific, factual, well-organized answers with concrete details. Be concise but comprehensive."
    full_prompt = f"{context}\n\n{query}" if context else query
    result = await _call_model(target, full_prompt, system)
    return f"[Research by {target}]\n\n{result}"


@mcp.tool()
async def delegate_code_generation(
    description: str,
    language: str = "python",
    context: str = "",
    model: str = "",
) -> str:
    """Delegate code generation to a free local coding model. Use this for boilerplate,
    utility functions, CRUD operations, standard patterns, tests, or any code that
    doesn't require complex architectural decisions.

    Args:
        description: What code to generate and its requirements.
        language: Programming language (default: python).
        context: Optional existing code or file context.
        model: Specific model (default: qwen2.5-coder:7b, free).
    """
    target = model or ROUTING["code"]
    system = f"You are an expert {language} developer. Write clean, production-ready code. Include type hints where appropriate. No unnecessary comments. Output ONLY the code unless explanation is specifically needed."
    full_prompt = f"Context:\n```\n{context}\n```\n\nGenerate: {description}" if context else description
    result = await _call_model(target, full_prompt, system)
    return f"[Code by {target}]\n\n{result}"


@mcp.tool()
async def delegate_code_review(
    code: str,
    focus: str = "bugs, security, performance, readability",
    language: str = "",
    model: str = "",
) -> str:
    """Delegate code review to a free coding model. Use this to get a second opinion
    on code quality, find bugs, check for security issues, or get optimization suggestions.

    Args:
        code: The code to review.
        focus: What to focus the review on.
        language: Programming language hint.
        model: Specific model (default: deepseek-coder:33b for thorough review).
    """
    target = model or ROUTING["code_heavy"]
    system = "You are a senior code reviewer. Be specific and actionable. Flag real issues, not style preferences. Prioritize: security vulnerabilities > bugs > performance > readability."
    prompt = f"Review this {language} code. Focus on: {focus}\n\n```{language}\n{code}\n```"
    result = await _call_model(target, prompt, system)
    return f"[Review by {target}]\n\n{result}"


@mcp.tool()
async def delegate_analysis(
    text: str,
    question: str,
    model: str = "",
) -> str:
    """Delegate text/data analysis to a free local model. Use this for analyzing logs,
    error messages, configuration files, data patterns, or any analytical task.

    Args:
        text: The text or data to analyze.
        question: What specific question to answer about the text.
        model: Specific model (default: qwen2.5, free).
    """
    target = model or ROUTING["analysis"]
    system = "You are a precise analyst. Answer the specific question asked. Be direct and evidence-based."
    prompt = f"Data:\n```\n{text}\n```\n\nQuestion: {question}"
    result = await _call_model(target, prompt, system)
    return f"[Analysis by {target}]\n\n{result}"


@mcp.tool()
async def delegate_summarize(
    text: str,
    max_words: int = 200,
    focus: str = "",
    model: str = "",
) -> str:
    """Delegate text summarization to a free local model. Use this to condense long
    outputs, documentation, logs, or any verbose text before processing it further.

    Args:
        text: The text to summarize.
        max_words: Target summary length in words (default: 200).
        focus: Optional focus area for the summary.
        model: Specific model (default: dolphin-llama3:8b, fastest free).
    """
    target = model or ROUTING["fast"]
    system = f"Summarize concisely in {max_words} words or fewer. Be precise and keep key details."
    prompt = f"Summarize this{' focusing on ' + focus if focus else ''}:\n\n{text}"
    result = await _call_model(target, prompt, system, max_tokens=1024)
    return f"[Summary by {target}]\n\n{result}"


@mcp.tool()
async def delegate_creative(
    task: str,
    context: str = "",
    model: str = "",
) -> str:
    """Delegate creative writing tasks to a free uncensored model. Use for marketing
    copy, product descriptions, blog posts, email sequences, social media content,
    or any creative text generation.

    Args:
        task: The creative task description.
        context: Brand/tone/audience context.
        model: Specific model (default: dolphin-mistral, free uncensored).
    """
    target = model or ROUTING["creative"]
    system = "You are a world-class copywriter and content creator. Write compelling, engaging content that drives action. Be creative and bold."
    prompt = f"{context}\n\n{task}" if context else task
    result = await _call_model(target, prompt, system)
    return f"[Creative by {target}]\n\n{result}"


@mcp.tool()
async def ask_model(
    prompt: str,
    model: str,
    system: str = "",
    max_tokens: int = 4096,
) -> str:
    """Send a prompt directly to any specific model in the AI mesh. Use this when
    you need a particular model's capabilities or want to compare responses.

    Args:
        prompt: The prompt to send.
        model: The model ID (e.g., 'grok-3-mini', 'qwen2.5-coder:7b', 'claude-sonnet-4-5').
        system: Optional system prompt.
        max_tokens: Maximum response tokens.
    """
    result = await _call_model(model, prompt, system, max_tokens)
    cost = MODELS.get(model, {}).get("cost", "unknown")
    return f"[{model} ({cost})]\n\n{result}"


@mcp.tool()
async def multi_model_ask(
    prompt: str,
    models: str = "",
    system: str = "",
) -> str:
    """Ask multiple models the same question in parallel and compare responses.
    Great for getting diverse perspectives or validating important decisions.

    Args:
        prompt: The question or task.
        models: Comma-separated model IDs (default: one free + one cheap model).
        system: Optional system prompt for all models.
    """
    if models:
        model_list = [m.strip() for m in models.split(",")]
    else:
        model_list = [ROUTING["general"], ROUTING["reasoning"]]

    results = await _call_multiple(model_list, prompt, system)

    output = []
    for model, response in results.items():
        cost = MODELS.get(model, {}).get("cost", "unknown")
        output.append(f"--- {model} ({cost}) ---\n{response}")

    return "\n\n".join(output)


@mcp.tool()
async def delegate_debug(
    error_message: str,
    code_context: str = "",
    stack_trace: str = "",
    model: str = "",
) -> str:
    """Delegate error analysis and debugging to a coding model. Use this to get
    quick analysis of errors, stack traces, and potential fixes before spending
    Opus tokens on debugging.

    Args:
        error_message: The error message.
        code_context: Relevant code that produced the error.
        stack_trace: Full stack trace if available.
        model: Specific model (default: deepseek-coder:33b).
    """
    target = model or ROUTING["code_heavy"]
    system = "You are a debugging expert. Analyze the error, identify the root cause, and suggest specific fixes. Be direct."
    parts = [f"Error: {error_message}"]
    if stack_trace:
        parts.append(f"Stack trace:\n```\n{stack_trace}\n```")
    if code_context:
        parts.append(f"Code:\n```\n{code_context}\n```")
    prompt = "\n\n".join(parts) + "\n\nWhat's the root cause and how do I fix it?"
    result = await _call_model(target, prompt, system)
    return f"[Debug analysis by {target}]\n\n{result}"


@mcp.tool()
async def delegate_architecture(
    description: str,
    constraints: str = "",
    model: str = "",
) -> str:
    """Delegate architecture/design questions to a reasoning model. Use for system
    design, tech stack decisions, API design, database schema design, or any
    architectural question that benefits from a second opinion.

    Args:
        description: The system or feature to design.
        constraints: Technical constraints, requirements, or preferences.
        model: Specific model (default: grok-3-mini, good reasoning).
    """
    target = model or ROUTING["reasoning"]
    system = "You are a senior software architect. Design practical, scalable systems. Prefer simplicity over complexity. Consider trade-offs explicitly."
    prompt = f"Design: {description}"
    if constraints:
        prompt += f"\n\nConstraints: {constraints}"
    result = await _call_model(target, prompt, system)
    return f"[Architecture by {target}]\n\n{result}"


@mcp.tool()
async def delegate_test_generation(
    code: str,
    framework: str = "pytest",
    language: str = "python",
    model: str = "",
) -> str:
    """Delegate test writing to a coding model. Use this to generate unit tests,
    integration tests, or test cases for existing code.

    Args:
        code: The code to write tests for.
        framework: Test framework (default: pytest).
        language: Programming language.
        model: Specific model (default: qwen2.5-coder:7b, free).
    """
    target = model or ROUTING["code"]
    system = f"You are a test engineer. Write thorough {framework} tests. Cover happy path, edge cases, and error cases. Output ONLY test code."
    prompt = f"Write {framework} tests for this {language} code:\n\n```{language}\n{code}\n```"
    result = await _call_model(target, prompt, system)
    return f"[Tests by {target}]\n\n{result}"


@mcp.tool()
async def mesh_status() -> str:
    """Check the health status of all AI mesh services. Returns which models
    and services are currently available."""
    services = {
        "AI Router": f"{ROUTER_URL}/health",
        "Ollama": f"{OLLAMA_URL}/",
    }

    async with httpx.AsyncClient(timeout=5) as client:
        results = []
        for name, url in services.items():
            try:
                resp = await client.get(url)
                results.append(f"  OK  {name} ({url})")
            except Exception as e:
                results.append(f"  DOWN  {name} ({url}) — {e}")

        # Check available Ollama models
        try:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            models = resp.json().get("models", [])
            model_names = [m["name"] for m in models]
            results.append(f"\nOllama models: {', '.join(model_names)}")
        except Exception:
            results.append("\nOllama models: unable to fetch")

    return "AI Mesh Status:\n" + "\n".join(results)


@mcp.tool()
async def list_models() -> str:
    """List all available models with their cost tier and capabilities."""
    lines = ["Available Models:\n"]
    for model_id, info in MODELS.items():
        cost_emoji = {"free": "FREE", "cheap": "$", "expensive": "$$$"}[info["cost"]]
        lines.append(f"  [{cost_emoji:>4}] {model_id:<30} — {info['good_at']}")
    lines.append(f"\nDefault routing:")
    for task, model in ROUTING.items():
        lines.append(f"  {task:<12} → {model}")
    return "\n".join(lines)


@mcp.tool()
async def roundtable_ask(
    question: str,
    participants: str = "CEO,CFO,CTO,Risk Manager",
) -> str:
    """Ask a question to the AI Roundtable and get responses from multiple
    specialized agents. Great for business decisions, strategy, or getting
    diverse expert perspectives.

    Args:
        question: The question to ask the roundtable.
        participants: Comma-separated agent names to include.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            # Get participant list from roundtable
            resp = await client.get(f"http://localhost:8130/health")
            resp.raise_for_status()
        except Exception as e:
            return f"[Roundtable unavailable: {e}]"

    # Use the router to call each participant's model with their persona
    # For now, fan out to 3 key agents
    agent_configs = {
        "CEO": {"model": "claude-sonnet-4-5", "system": "You are the CEO — a visionary leader focused on ROI, scalability, and fast time-to-revenue."},
        "CFO": {"model": "claude-sonnet-4-5", "system": "You are the CFO — you analyze unit economics, margins, break-even, and enforce spending limits."},
        "CTO": {"model": "claude-sonnet-4-5", "system": "You are the CTO — you evaluate technical feasibility, pick stacks, estimate effort, and flag risks."},
        "Risk Manager": {"model": "qwen2.5:latest", "system": "You are the Risk Manager — you identify what can go wrong and assign probability/severity."},
        "Market Researcher": {"model": "grok-3-mini", "system": "You are the Market Researcher — you find data-driven insights on market size, competitors, and trends."},
        "Devil's Advocate": {"model": "nous-hermes2:latest", "system": "You are the Devil's Advocate — you challenge assumptions and find fatal flaws."},
    }

    selected = [p.strip() for p in participants.split(",")]
    tasks = {}
    for name in selected:
        if name in agent_configs:
            cfg = agent_configs[name]
            tasks[name] = _call_model(cfg["model"], question, cfg["system"], max_tokens=2048)

    if not tasks:
        return f"No matching agents found. Available: {', '.join(agent_configs.keys())}"

    output = [f"Roundtable Discussion: {question}\n"]
    for name, coro in tasks.items():
        response = await coro
        model = agent_configs[name]["model"]
        cost = MODELS.get(model, {}).get("cost", "?")
        output.append(f"--- {name} [{model}, {cost}] ---\n{response}\n")

    return "\n".join(output)


@mcp.tool()
async def delegate_batch(
    tasks_json: str,
) -> str:
    """Run multiple delegation tasks in parallel. Each task specifies a model
    and prompt. Returns all results. Great for fan-out operations.

    Args:
        tasks_json: JSON array of tasks, each with 'model', 'prompt', and optional 'system'.
                    Example: [{"model": "qwen2.5-coder:7b", "prompt": "Write a hello world"},
                              {"model": "grok-3-mini", "prompt": "What is Python?"}]
    """
    try:
        task_list = json.loads(tasks_json)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"

    coros = []
    labels = []
    for i, task in enumerate(task_list):
        model = task.get("model", ROUTING["general"])
        prompt = task.get("prompt", "")
        system = task.get("system", "")
        if prompt:
            coros.append(_call_model(model, prompt, system))
            labels.append(f"Task {i+1} [{model}]")

    results = await asyncio.gather(*coros, return_exceptions=True)

    output = []
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            output.append(f"--- {label} ---\nError: {result}")
        else:
            output.append(f"--- {label} ---\n{result}")

    return "\n\n".join(output)


if __name__ == "__main__":
    mcp.run(transport="stdio")
