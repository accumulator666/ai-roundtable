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

# Models that should route to R730 (big models that need 24GB VRAM / 128GB RAM)
R730_MODELS = {
    "deepseek-coder:33b",
    "llama3.1:70b",
    "qwen2.5:72b",
    "codellama:34b",
    "mixtral:8x7b",
    "llama3.1:8b",  # can offload to R730 when local is busy
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


def resolve_proxy_url(model: str) -> str:
    proxy_name = MODEL_TO_PROXY.get(model)
    if not proxy_name:
        # Local Ollama model — check if it should go to R730
        if model in R730_MODELS:
            return PROXY_MAP["ollama-r730"]
        return PROXY_MAP["ollama"]
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
