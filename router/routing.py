import re
import httpx

PROXY_MAP = {
    "claude-proxy": "http://claude-proxy:8000",
    "chatgpt-proxy": "http://chatgpt-proxy:8000",
    "grok-proxy": "http://grok-proxy:8000",
    "gemini-proxy": "http://gemini-proxy:8000",
    "deepseek-proxy": "http://deepseek-proxy:8000",
    "ollama": "http://ollama:11434",
    "claude-code": "http://claude-code:8000",
}

MODEL_TO_PROXY = {
    "claude-opus-4-6": "claude-proxy",
    "claude-sonnet-4-5": "claude-proxy",
    "claude-haiku-4-5": "claude-proxy",
    "gpt-4o": "chatgpt-proxy",
    "gpt-4o-mini": "chatgpt-proxy",
    "gpt-4-turbo": "chatgpt-proxy",
    "o1": "chatgpt-proxy",
    "o3-mini": "chatgpt-proxy",
    "grok-3": "grok-proxy",
    "grok-3-mini": "grok-proxy",
    "gemini-2.0-flash": "gemini-proxy",
    "gemini-2.0-pro": "gemini-proxy",
    "gemini-1.5-pro": "gemini-proxy",
    "deepseek-chat": "deepseek-proxy",
    "deepseek-reasoner": "deepseek-proxy",
    "claude-code": "claude-code",
}

AUTO_ROUTE_PATTERNS = {
    "coding": (r"\b(code|program|debug|function|class|refactor|implement|bug|error|script)\b", "claude-opus-4-6"),
    "creative": (r"\b(write|story|poem|creative|blog|essay|marketing|copy)\b", "gpt-4o"),
    "research": (r"\b(research|analyze|compare|data|statistics|report|study)\b", "grok-3"),
    "multimodal": (r"\b(image|picture|photo|visual|diagram|chart)\b", "gemini-2.0-flash"),
}


def resolve_proxy_url(model: str) -> str:
    proxy_name = MODEL_TO_PROXY.get(model)
    if not proxy_name:
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
                if name == "ollama":
                    # Ollama uses GET / which returns "Ollama is running"
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        statuses[name] = {"status": "ok", "service": "ollama", "models": []}
                    else:
                        statuses[name] = {"status": "error"}
                else:
                    resp = await client.get(f"{url}/health")
                    statuses[name] = resp.json() if resp.status_code == 200 else {"status": "error"}
            except Exception:
                statuses[name] = {"status": "unreachable"}
    return statuses
