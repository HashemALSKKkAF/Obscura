"""Tests for the provider registry (providers.py)."""
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

import providers


def test_is_set_rejects_placeholders():
    assert providers.is_set("sk-real") is True
    assert providers.is_set("sk-or-v1-abc123") is True
    assert providers.is_set("") is False
    assert providers.is_set(None) is False
    assert providers.is_set("your_key_here") is False
    assert providers.is_set("<your api key>") is False   # the .env default that caused a 401
    assert providers.is_set("changeme") is False


def test_provider_is_configured_reads_env_live(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live")
    assert providers.get("openai").is_configured() is True
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert providers.get("openai").is_configured() is False


def test_resolve_static_openai_has_no_injected_secret():
    cfg = providers.resolve_static("gpt-4.1")
    assert cfg["class"] is ChatOpenAI
    assert cfg["constructor_params"] == {"model_name": "gpt-4.1"}


def test_resolve_static_openrouter_injects_live_credentials(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-live")
    cfg = providers.resolve_static("qwen3-80b-openrouter")
    assert cfg["class"] is ChatOpenAI
    assert cfg["constructor_params"]["api_key"] == "sk-or-live"
    assert "openrouter" in cfg["constructor_params"]["base_url"]


def test_resolve_static_google_injects_live_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g-live")
    cfg = providers.resolve_static("gemini-2.5-flash")
    assert cfg["constructor_params"]["google_api_key"] == "g-live"


def test_resolve_static_unknown_is_none():
    assert providers.resolve_static("not-a-model") is None


def test_provider_for_model():
    assert providers.provider_for_model("gpt-4.1").key == "openai"
    assert providers.provider_for_model("claude-sonnet-4-5").key == "anthropic"
    assert providers.provider_for_model("qwen3-80b-openrouter").key == "openrouter"
    assert providers.provider_for_model("some-local-ollama-model") is None  # dynamic/local


def test_label_for_resolved():
    assert providers.label_for_resolved(ChatAnthropic, {}) == "Anthropic"
    assert providers.label_for_resolved(ChatOpenAI, {}) == "OpenAI"
    assert providers.label_for_resolved(ChatOpenAI, {"base_url": "https://openrouter.ai/api/v1"}) == "OpenRouter"
    assert providers.label_for_resolved(ChatOpenAI, {"base_url": "http://localhost:8080"}) == "llama.cpp (local)"
