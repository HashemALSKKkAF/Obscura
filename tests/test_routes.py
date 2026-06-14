"""Flask test-client tests for the blueprint wiring (no network/Tor/keys)."""
import pytest

import app as app_module


@pytest.fixture
def client(temp_db):
    application = app_module.create_app()
    application.config.update(TESTING=True)
    return application.test_client()


def test_index_served(client):
    assert client.get("/").status_code == 200


def test_spa_fallback_for_unknown_path(client):
    # Unknown non-file path falls back to the SPA entry point.
    assert client.get("/some/client/route").status_code == 200


def test_investigations_empty_on_fresh_db(client):
    resp = client.get("/api/investigations")
    assert resp.status_code == 200
    assert resp.get_json() == {"investigations": [], "tags": []}


def test_presets_returns_builtins(client):
    resp = client.get("/api/presets")
    assert resp.status_code == 200
    presets = resp.get_json()["presets"]
    keys = {p["key"] for p in presets}
    assert {"threat_intel", "ransomware_malware", "personal_identity", "corporate_espionage"} <= keys
    assert all(p["system_prompt"] for p in presets)


def test_providers_status_lists_all(client):
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    names = {p["name"] for p in resp.get_json()["providers"]}
    assert {"OpenAI", "Anthropic", "Google", "OpenRouter", "Ollama", "llama.cpp"} == names


def test_provider_save_rejects_unknown_key(client):
    resp = client.post("/api/providers", json={"envKey": "NOT_A_KEY", "value": "x"})
    assert resp.status_code == 400


def test_provider_save_rejects_empty_value(client):
    resp = client.post("/api/providers", json={"envKey": "OPENAI_API_KEY", "value": ""})
    assert resp.status_code == 400


def test_investigate_requires_query(client):
    assert client.post("/api/investigate", json={"model": "gpt-4.1"}).status_code == 400


def test_investigate_requires_model(client):
    assert client.post("/api/investigate", json={"query": "x"}).status_code == 400


def test_investigate_rejects_model_without_credentials(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = client.post("/api/investigate", json={"query": "x", "model": "gpt-4.1"})
    assert resp.status_code == 400
    assert "OPENAI_API_KEY" in resp.get_json()["error"]


def test_export_pdf_roundtrip(client):
    resp = client.post("/api/export/pdf", json={
        "summary": "# Findings\n\nSome **text**.",
        "metadata": {"query": "q", "model": "gpt-4.1"},
    })
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "application/pdf"
    assert resp.data[:4] == b"%PDF"


def test_export_pdf_requires_summary(client):
    assert client.post("/api/export/pdf", json={}).status_code == 400


def test_tor_newnym_reports_exit_ip(client, monkeypatch):
    import tor_session
    import tor_utils
    monkeypatch.setattr(tor_utils, "refresh_tor_circuit", lambda *a, **k: {"status": "ok", "message": "rotated"})
    monkeypatch.setattr(tor_session, "get_tor_session", lambda: object())
    monkeypatch.setattr(tor_utils, "get_tor_exit_ip", lambda session: "1.2.3.4")
    body = client.post("/api/tor/newnym").get_json()
    assert body["status"] == "ok"
    assert body["exit_ip"] == "1.2.3.4"


def test_tor_newnym_error_passthrough(client, monkeypatch):
    import tor_utils
    monkeypatch.setattr(tor_utils, "refresh_tor_circuit", lambda *a, **k: {"status": "error", "message": "no control port"})
    body = client.post("/api/tor/newnym").get_json()
    assert body["status"] == "error"


def test_as_bool_coercion():
    from api_investigations import _as_bool
    assert _as_bool(True) is True
    assert _as_bool("true") is True and _as_bool("1") is True and _as_bool("yes") is True
    assert _as_bool("false") is False and _as_bool(None) is False
    assert _as_bool("nonsense") is False
