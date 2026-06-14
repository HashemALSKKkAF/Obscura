"""Characterization tests for obscura_config._clean_env."""
import obscura_config


def test_clean_env_strips_whitespace(monkeypatch):
    monkeypatch.setenv("OBS_TEST_KEY", "  hello  ")
    assert obscura_config._clean_env("OBS_TEST_KEY") == "hello"


def test_clean_env_strips_matching_double_quotes(monkeypatch):
    monkeypatch.setenv("OBS_TEST_KEY", '"quoted"')
    assert obscura_config._clean_env("OBS_TEST_KEY") == "quoted"


def test_clean_env_strips_matching_single_quotes(monkeypatch):
    monkeypatch.setenv("OBS_TEST_KEY", "'quoted'")
    assert obscura_config._clean_env("OBS_TEST_KEY") == "quoted"


def test_clean_env_leaves_mismatched_quotes(monkeypatch):
    monkeypatch.setenv("OBS_TEST_KEY", "'mismatched\"")
    assert obscura_config._clean_env("OBS_TEST_KEY") == "'mismatched\""


def test_clean_env_missing_returns_default(monkeypatch):
    monkeypatch.delenv("OBS_TEST_MISSING", raising=False)
    assert obscura_config._clean_env("OBS_TEST_MISSING") is None
    assert obscura_config._clean_env("OBS_TEST_MISSING", "fallback") == "fallback"
