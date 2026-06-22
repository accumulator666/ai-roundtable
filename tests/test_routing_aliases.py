import os
import sys

# routing.py lives in router/ and is imported there as a top-level module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "router"))

from routing import resolve_model_name, resolve_proxy_url, R730_MODELS, PROXY_MAP


def test_qwen3_30b_resolves_to_exact_r730_tag():
    """Participants reference the bare tag 'qwen3:30b'; it must resolve to the
    exact tag R730 serves, or the router forwards an unknown name and Ollama 404s."""
    resolved = resolve_model_name("qwen3:30b")
    assert resolved == "qwen3:30b-a3b-instruct-2507-q4_K_M"
    assert resolved in R730_MODELS


def test_qwen3_30b_routes_to_r730():
    """After alias resolution the model must route to the R730 Ollama proxy."""
    assert resolve_proxy_url("qwen3:30b") == PROXY_MAP["ollama-r730"]
