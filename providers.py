"""
providers.py
Single source of truth for OBSCURA's LLM providers and their models.

Provider knowledge used to be duplicated as parallel ``if/elif`` chains in
llm.py (credential checks), health.py (display labels) and app.py (the provider
settings UI). Centralizing it here means **adding a provider is one entry**, not
edits scattered across three files (Open/Closed Principle).

Credentials are read **live** from obscura_config at the moment a model is built
or gated, so a key saved through the UI (which writes os.environ) takes effect
immediately — no module reloading, which is what the old code resorted to.
"""
from dataclasses import dataclass, field

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI

import obscura_config


_PLACEHOLDER_MARKERS = ("your", "<", ">", "changeme", "placeholder", "api_key_here", "xxxx")


def is_set(value) -> bool:
    """A configuration value counts as set if it's non-empty and not an obvious
    placeholder (e.g. ``your_key``, ``<your api key>``, ``changeme``).

    Real keys/URLs never contain these markers, so this prevents a provider
    whose .env value is still a template from showing up as configured (which
    otherwise surfaces later as a confusing 401 from the provider)."""
    if not value:
        return False
    v = str(value).strip().lower()
    if not v:
        return False
    return not any(marker in v for marker in _PLACEHOLDER_MARKERS)


@dataclass(frozen=True)
class Provider:
    key: str            # internal id, e.g. "openai"
    name: str           # display label, e.g. "OpenAI"
    env_var: str        # the env var that configures it
    field_kind: str     # "key" | "url" — how the UI should render its input
    is_cloud: bool      # hosted (key required) vs. local (optional)

    def credential(self) -> "str | None":
        """The current value of this provider's env var (read live)."""
        return obscura_config._clean_env(self.env_var)

    def is_configured(self) -> bool:
        return is_set(self.credential())


# Order mirrors the provider settings UI.
PROVIDERS = [
    Provider("openai", "OpenAI", "OPENAI_API_KEY", "key", is_cloud=True),
    Provider("anthropic", "Anthropic", "ANTHROPIC_API_KEY", "key", is_cloud=True),
    Provider("google", "Google", "GOOGLE_API_KEY", "key", is_cloud=True),
    Provider("openrouter", "OpenRouter", "OPENROUTER_API_KEY", "key", is_cloud=True),
    Provider("ollama", "Ollama", "OLLAMA_BASE_URL", "url", is_cloud=False),
    Provider("llama_cpp", "llama.cpp", "LLAMA_CPP_BASE_URL", "url", is_cloud=False),
]

_BY_KEY = {p.key: p for p in PROVIDERS}
_BY_ENV = {p.env_var: p for p in PROVIDERS}


def get(provider_key: str) -> "Provider | None":
    return _BY_KEY.get(provider_key)


def by_env(env_var: str) -> "Provider | None":
    return _BY_ENV.get(env_var)


@dataclass(frozen=True)
class ModelSpec:
    """A statically-known model and the provider/class that serves it.

    ``params`` carries only non-secret constructor arguments (the model name).
    Secrets/URLs are injected live by :func:`build_params`.
    """
    name: str            # the model choice key the UI shows, e.g. "gpt-4.1"
    provider: str        # provider key
    chat_class: type     # LangChain chat-model class
    params: dict = field(default_factory=dict)


# Order is preserved as the default model-picker ordering.
STATIC_MODELS = [
    ModelSpec("gpt-4.1", "openai", ChatOpenAI, {"model_name": "gpt-4.1"}),
    ModelSpec("gpt-5.2", "openai", ChatOpenAI, {"model_name": "gpt-5.2"}),
    ModelSpec("gpt-5.1", "openai", ChatOpenAI, {"model_name": "gpt-5.1"}),
    ModelSpec("gpt-5-mini", "openai", ChatOpenAI, {"model_name": "gpt-5-mini"}),
    ModelSpec("gpt-5-nano", "openai", ChatOpenAI, {"model_name": "gpt-5-nano"}),
    ModelSpec("claude-sonnet-4-5", "anthropic", ChatAnthropic, {"model": "claude-sonnet-4-5"}),
    ModelSpec("claude-sonnet-4-0", "anthropic", ChatAnthropic, {"model": "claude-sonnet-4-0"}),
    ModelSpec("gemini-2.5-flash", "google", ChatGoogleGenerativeAI, {"model": "gemini-2.5-flash"}),
    ModelSpec("gemini-2.5-flash-lite", "google", ChatGoogleGenerativeAI, {"model": "gemini-2.5-flash-lite"}),
    ModelSpec("gemini-2.5-pro", "google", ChatGoogleGenerativeAI, {"model": "gemini-2.5-pro"}),
    ModelSpec("qwen3-80b-openrouter", "openrouter", ChatOpenAI, {"model_name": "qwen/qwen3-next-80b-a3b-instruct:free"}),
    ModelSpec("nemotron-nano-9b-openrouter", "openrouter", ChatOpenAI, {"model_name": "nvidia/nemotron-nano-9b-v2:free"}),
    ModelSpec("gpt-oss-120b-openrouter", "openrouter", ChatOpenAI, {"model_name": "openai/gpt-oss-120b:free"}),
    ModelSpec("gpt-5.1-openrouter", "openrouter", ChatOpenAI, {"model_name": "openai/gpt-5.1"}),
    ModelSpec("gpt-5-mini-openrouter", "openrouter", ChatOpenAI, {"model_name": "openai/gpt-5-mini"}),
    ModelSpec("claude-sonnet-4.5-openrouter", "openrouter", ChatOpenAI, {"model_name": "anthropic/claude-sonnet-4.5"}),
    ModelSpec("grok-4.1-fast-openrouter", "openrouter", ChatOpenAI, {"model_name": "x-ai/grok-4.1-fast"}),
]


def build_params(spec: ModelSpec) -> dict:
    """Constructor params for a model, injecting live credentials/URLs."""
    params = dict(spec.params)
    if spec.provider == "google":
        params["google_api_key"] = obscura_config.google_api_key()
    elif spec.provider == "openrouter":
        params["base_url"] = obscura_config.openrouter_base_url()
        params["api_key"] = obscura_config.openrouter_api_key()
    return params


def resolve_static(model_choice: str) -> "dict | None":
    """Resolve a statically-known model (no network). Returns the
    ``{"class", "constructor_params"}`` shape, or None if unknown."""
    norm = (model_choice or "").strip().lower()
    for spec in STATIC_MODELS:
        if spec.name.lower() == norm:
            return {"class": spec.chat_class, "constructor_params": build_params(spec)}
    return None


def configured_static_model_names() -> list:
    """Static model names whose provider currently has its credential set."""
    return [s.name for s in STATIC_MODELS if get(s.provider).is_configured()]


def provider_for_model(model_choice: str) -> "Provider | None":
    """The provider serving a statically-known model. Dynamic local models
    (Ollama / llama.cpp) return None — they need no cloud credential."""
    norm = (model_choice or "").strip().lower()
    for spec in STATIC_MODELS:
        if spec.name.lower() == norm:
            return get(spec.provider)
    return None


def label_for_resolved(chat_class, params: dict) -> str:
    """Human label for an already-resolved model config, including dynamic
    local models that aren't in STATIC_MODELS. Used by health checks."""
    class_name = getattr(chat_class, "__name__", str(chat_class))
    base_url = (params.get("base_url") or "").lower()
    if "ChatAnthropic" in class_name:
        return "Anthropic"
    if "ChatGoogleGenerativeAI" in class_name:
        return "Google Gemini"
    if "ChatOllama" in class_name:
        return "Ollama (local)"
    if "ChatOpenAI" in class_name:
        if "openrouter" in base_url:
            return "OpenRouter"
        if any(x in base_url for x in ("llama", "localhost", "127.0.0.1")):
            return "llama.cpp (local)"
        return "OpenAI"
    return class_name
