import os
import re
import httpx

# R730 IP — override with R730_OLLAMA_URL env var
R730_URL = os.environ.get("R730_OLLAMA_URL", "http://10.0.0.2:11434")

PROXY_MAP = {
    "claude-proxy": "http://claude-proxy:8000",
    "chatgpt-proxy": "http://chatgpt-proxy:8000",
    "grok-proxy": "http://grok-proxy:8000",
    "gemini-proxy": "http://gemini-proxy:8000",
    "deepseek-proxy": "http://deepseek-proxy:8000",
    "ollama": "http://ollama:11434",
    "ollama-r730": R730_URL,
    "claude-code": "http://claude-code:8000",
}

# Models available on R730 (192.168.50.179 / 10.0.0.2 via 10G SFP+)
# Tesla M40 24GB VRAM, 128GB RAM. Updated 2026-03-24.
R730_MODELS = {
    "deepseek-coder:33b",
    "deepseek-r1:32b",
    "qwen2.5:32b",
    "qwen2.5:7b",
    "qwen2.5-coder:7b",
    "wizardlm-uncensored:13b",
    "dolphin-mixtral:latest",
    "dolphin-llama3:8b",
    "dolphin-mistral:latest",
    "nous-hermes2:latest",
}

MODEL_TO_PROXY = {
    # Anthropic — routed through claude-code to use Max subscription
    "claude-opus-4-6": "claude-code",
    "claude-sonnet-4-5": "claude-code",
    "claude-haiku-4-5": "claude-code",
    # OpenAI — GPT-5.x family (current)
    "gpt-5.2": "chatgpt-proxy",
    "gpt-5": "chatgpt-proxy",
    "gpt-5-mini": "chatgpt-proxy",
    "gpt-5-nano": "chatgpt-proxy",
    # OpenAI — reasoning models
    "o4-mini": "chatgpt-proxy",
    "o3": "chatgpt-proxy",
    "o3-mini": "chatgpt-proxy",
    "o1": "chatgpt-proxy",
    "o1-pro": "chatgpt-proxy",
    # OpenAI — legacy (retiring Feb 13 2026)
    "gpt-4o": "chatgpt-proxy",
    "gpt-4o-mini": "chatgpt-proxy",
    "gpt-4-turbo": "chatgpt-proxy",
    # xAI — Grok 4.x series
    "grok-4-1-fast-reasoning": "grok-proxy",
    "grok-4-1-fast-non-reasoning": "grok-proxy",
    "grok-4-fast-reasoning": "grok-proxy",
    "grok-4-fast-non-reasoning": "grok-proxy",
    "grok-4-0709": "grok-proxy",
    "grok-code-fast-1": "grok-proxy",
    # xAI — Grok 3.x legacy
    "grok-3": "grok-proxy",
    "grok-3-mini": "grok-proxy",
    # Google
    "gemini-2.0-flash": "gemini-proxy",
    "gemini-2.0-pro": "gemini-proxy",
    "gemini-1.5-pro": "gemini-proxy",
    # DeepSeek
    "deepseek-chat": "deepseek-proxy",
    "deepseek-reasoner": "deepseek-proxy",
    # Claude Code
    "claude-code": "claude-code",
}

AUTO_ROUTE_PATTERNS = {
    "coding": (r"\b(code|program|debug|function|class|refactor|implement|bug|error|script)\b", "gpt-5.2"),
    "creative": (r"\b(write|story|poem|creative|blog|essay|marketing|copy)\b", "gpt-5.2"),
    "research": (r"\b(research|analyze|compare|data|statistics|report|study)\b", "grok-3"),
    "multimodal": (r"\b(image|picture|photo|visual|diagram|chart)\b", "gemini-2.0-flash"),
}


# Alias :latest tags to exact tags available on R730
MODEL_ALIASES = {
    "qwen2.5:latest": "qwen2.5:7b",
    "qwen2.5-coder:latest": "qwen2.5-coder:7b",
    "nous-hermes2": "nous-hermes2:latest",
    "dolphin-llama3": "dolphin-llama3:8b",
    "dolphin-mistral": "dolphin-mistral:latest",
    "dolphin-mixtral": "dolphin-mixtral:latest",
    "deepseek-coder": "deepseek-coder:33b",
    "deepseek-r1": "deepseek-r1:32b",
    "wizardlm-uncensored": "wizardlm-uncensored:13b",
    "qwen2.5": "qwen2.5:7b",
}


def resolve_model_name(model: str) -> str:
    """Resolve aliases and :latest tags to exact model names available on R730."""
    if model in MODEL_ALIASES:
        return MODEL_ALIASES[model]
    return model


def resolve_proxy_url(model: str) -> str:
    proxy_name = MODEL_TO_PROXY.get(model)
    if not proxy_name:
        # Check if it should go to R730
        resolved = resolve_model_name(model)
        if resolved in R730_MODELS or model in R730_MODELS:
            return PROXY_MAP["ollama-r730"]
        # Check if base name matches any R730 model
        model_base = model.split(":")[0]
        for r730_model in R730_MODELS:
            if r730_model.split(":")[0] == model_base:
                return PROXY_MAP["ollama-r730"]
        # Fallback: try R730 (local Ollama may not be running)
        return PROXY_MAP["ollama-r730"]
    return PROXY_MAP[proxy_name]


def auto_select_model(messages: list[dict]) -> str:
    text = " ".join(m.get("content", "") for m in messages).lower()
    for category, (pattern, model) in AUTO_ROUTE_PATTERNS.items():
        if re.search(pattern, text):
            return model
    return "claude-sonnet-4-5"


async def get_all_models() -> list[dict]:
    all_models = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, url in PROXY_MAP.items():
            try:
                resp = await client.get(f"{url}/v1/models")
                if resp.status_code == 200:
                    data = resp.json()
                    all_models.extend(data.get("data", []))
            except Exception:
                continue
    return all_models


async def check_health() -> dict:
    statuses = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in PROXY_MAP.items():
            try:
                if name in ("ollama", "ollama-r730"):
                    # Ollama uses GET / which returns "Ollama is running"
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        statuses[name] = {"status": "ok", "service": name, "models": []}
                    else:
                        statuses[name] = {"status": "error"}
                else:
                    resp = await client.get(f"{url}/health")
                    statuses[name] = resp.json() if resp.status_code == 200 else {"status": "error"}
            except Exception:
                statuses[name] = {"status": "unreachable"}
    return statuses
