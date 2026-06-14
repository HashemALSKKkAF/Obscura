"""Tests for the unified tor_session module and lazy port resolution."""
import obscura_config
import tor_session


def test_build_session_uses_tor_proxy(monkeypatch):
    monkeypatch.setattr(obscura_config, "get_socks_port", lambda: 9999)
    session = tor_session._build_session(use_tor=True)
    assert session.proxies["http"] == "socks5h://127.0.0.1:9999"
    assert session.proxies["https"] == "socks5h://127.0.0.1:9999"


def test_build_session_without_tor_has_no_proxy():
    session = tor_session._build_session(use_tor=False)
    assert session.proxies == {}


def test_get_session_is_thread_local_cached(monkeypatch):
    monkeypatch.setattr(obscura_config, "get_socks_port", lambda: 9050)
    a = tor_session.get_session(use_tor=True)
    b = tor_session.get_session(use_tor=True)
    assert a is b  # same thread → cached instance


def test_probe_port_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("OBS_FAKE_PORT", "9999")
    assert obscura_config._probe_port([9150, 9050], "OBS_FAKE_PORT", 9150) == 9999


def test_probe_port_falls_back_when_unreachable(monkeypatch):
    monkeypatch.delenv("OBS_FAKE_PORT", raising=False)
    # Port 1 is not listening locally → refused immediately → fall back.
    assert obscura_config._probe_port([1], "OBS_FAKE_PORT", 12345) == 12345
