import os


def get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


PROXY_URLS = {
    "claude": "http://claude-proxy:8000",
    "chatgpt": "http://chatgpt-proxy:8000",
    "grok": "http://grok-proxy:8000",
    "gemini": "http://gemini-proxy:8000",
    "ollama": "http://ollama:11434",
    "claude-code": "http://claude-code:8000",
}

MODEL_ROUTING = {
    "claude-opus-4-6": "claude",
    "claude-sonnet-4-5": "claude",
    "claude-haiku-4-5": "claude",
    "gpt-4o": "chatgpt",
    "gpt-4o-mini": "chatgpt",
    "gpt-4-turbo": "chatgpt",
    "o1": "chatgpt",
    "o3-mini": "chatgpt",
    "grok-3": "grok",
    "grok-3-mini": "grok",
    "gemini-2.0-flash": "gemini",
    "gemini-2.0-pro": "gemini",
    "gemini-1.5-pro": "gemini",
    "claude-code": "claude-code",
}

AUTO_ROUTING = {
    "coding": "claude-opus-4-6",
    "creative": "gpt-4o",
    "research": "grok-3",
    "multimodal": "gemini-2.0-flash",
    "fast": "claude-haiku-4-5",
    "default": "claude-sonnet-4-5",
}
