"""
llm_utils.py
Streaming handler + model discovery/resolution.

The static model catalog and provider knowledge now live in providers.py; this
module keeps the streaming callback, the shared LLM params, and the model
discovery/resolution functions (which add live local-model discovery on top of
the static registry). Public names are preserved for llm.py / health.py / tests.
"""
from typing import Callable, List, Optional
from urllib.parse import urljoin

import requests
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langchain_core.callbacks.base import BaseCallbackHandler

import obscura_config
import providers


class BufferedStreamingHandler(BaseCallbackHandler):
    def __init__(self, buffer_limit: int = 60, ui_callback: Optional[Callable[[str], None]] = None):
        self.buffer = ""
        self.buffer_limit = buffer_limit
        self.ui_callback = ui_callback

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        self.buffer += token
        if "\n" in token or len(self.buffer) >= self.buffer_limit:
            print(self.buffer, end="", flush=True)
            if self.ui_callback:
                self.ui_callback(self.buffer)
            self.buffer = ""

    def on_llm_end(self, response, **kwargs) -> None:
        if self.buffer:
            print(self.buffer, end="", flush=True)
            if self.ui_callback:
                self.ui_callback(self.buffer)
            self.buffer = ""


# Common parameters shared by all LLMs. 'callbacks' is intentionally excluded; a
# fresh BufferedStreamingHandler is created per get_llm() call in llm.py to avoid
# a shared-singleton handler leaking ui_callback state between pipeline stages.
_common_llm_params = {
    "temperature": 0,
    "streaming": True,
}


def _normalize_model_name(name: str) -> str:
    return name.strip().lower()


# --- Local model discovery (network) ---------------------------------------

def _get_ollama_base_url() -> Optional[str]:
    base = obscura_config.ollama_base_url()
    if not base:
        return None
    return base.rstrip("/") + "/"


def fetch_ollama_models() -> List[str]:
    """
    Retrieve locally available Ollama models via the Ollama HTTP API.
    Returns [] if the API isn't reachable or no base URL is configured.
    """
    base_url = _get_ollama_base_url()
    if not base_url:
        return []
    try:
        resp = requests.get(urljoin(base_url, "api/tags"), timeout=3)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        available = []
        for m in models:
            name = m.get("name") or m.get("model")
            if name:
                available.append(name)
        return available
    except (requests.RequestException, ValueError):
        return []


def fetch_llama_cpp_models() -> List[str]:
    """Retrieve available models from an OpenAI-compatible llama.cpp server."""
    base = obscura_config.llama_cpp_base_url()
    if not base:
        return []
    base = base.rstrip("/")
    try:
        resp = requests.get(f"{base}/v1/models", timeout=3)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [m["id"] for m in data if "id" in m]
    except (requests.RequestException, ValueError, KeyError):
        return []


# --- Model choices + resolution --------------------------------------------

def get_model_choices() -> List[str]:
    """
    Combine configured static (cloud) models with locally available
    Ollama/llama.cpp models. Cloud models appear only if their provider's
    credential is set.
    """
    static_models = providers.configured_static_model_names()

    dynamic_models = fetch_ollama_models() + fetch_llama_cpp_models()

    normalized = {_normalize_model_name(m): m for m in static_models}
    for dm in dynamic_models:
        key = _normalize_model_name(dm)
        if key not in normalized:
            normalized[key] = dm

    ordered_dynamic = sorted(
        [name for name in normalized.values() if name not in static_models],
        key=_normalize_model_name,
    )
    return static_models + ordered_dynamic


def resolve_model_config(model_choice: str):
    """
    Resolve a model choice (case-insensitive) to ``{"class", "constructor_params"}``.
    Tries the static registry first, then locally-discovered llama.cpp/Ollama models.
    """
    static = providers.resolve_static(model_choice)
    if static:
        return static

    norm = _normalize_model_name(model_choice)

    for llama_model in fetch_llama_cpp_models():
        if _normalize_model_name(llama_model) == norm:
            return {
                "class": ChatOpenAI,
                "constructor_params": {
                    "model_name": llama_model,
                    "base_url": obscura_config.llama_cpp_base_url(),
                    "api_key": obscura_config.openai_api_key() or "sk-local",
                },
            }

    for ollama_model in fetch_ollama_models():
        if _normalize_model_name(ollama_model) == norm:
            return {
                "class": ChatOllama,
                "constructor_params": {
                    "model": ollama_model,
                    "base_url": obscura_config.ollama_base_url(),
                },
            }

    return None
