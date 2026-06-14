"""Characterization tests for llm_utils model-resolution logic (no network)."""
import llm_utils
from langchain_openai import ChatOpenAI


def test_normalize_model_name():
    assert llm_utils._normalize_model_name("  GPT-4.1 ") == "gpt-4.1"


# (the placeholder/empty "is set" contract is covered in test_providers.py)


def test_resolve_known_model_is_case_insensitive():
    cfg_lower = llm_utils.resolve_model_config("gpt-4.1")
    cfg_upper = llm_utils.resolve_model_config("GPT-4.1")
    assert cfg_lower is not None
    assert cfg_lower == cfg_upper
    assert cfg_lower["class"] is ChatOpenAI
    assert cfg_lower["constructor_params"]["model_name"] == "gpt-4.1"


def test_resolve_unknown_model_returns_none(monkeypatch):
    # Keep it hermetic: no local-model discovery calls.
    monkeypatch.setattr(llm_utils, "fetch_llama_cpp_models", lambda: [])
    monkeypatch.setattr(llm_utils, "fetch_ollama_models", lambda: [])
    assert llm_utils.resolve_model_config("totally-made-up-model") is None


def test_get_model_choices_gates_on_keys(monkeypatch):
    # Keys are now read live from the environment via the provider registry.
    monkeypatch.setattr(llm_utils, "fetch_ollama_models", lambda: [])
    monkeypatch.setattr(llm_utils, "fetch_llama_cpp_models", lambda: [])
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    choices = llm_utils.get_model_choices()

    assert "gpt-4.1" in choices            # OpenAI key present
    assert "claude-sonnet-4-5" not in choices   # Anthropic key absent
    assert "gemini-2.5-pro" not in choices      # Google key absent
    assert "qwen3-80b-openrouter" not in choices  # OpenRouter key absent
