"""
api_config.py
Configuration & meta endpoints: model list, provider keys, presets, health.
"""
import logging

from flask import Blueprint, jsonify, request

from __version__ import __version__
import env_manager
import presets as preset_db
from health import check_llm_health, check_search_engines, check_tor_proxy
from llm import PRESET_PROMPTS
from llm_utils import get_model_choices

config_bp = Blueprint("config", __name__)

_BUILTIN_PRESET_LABELS = [
    ("threat_intel", "🔍 Dark Web Threat Intel"),
    ("ransomware_malware", "🦠 Ransomware / Malware Focus"),
    ("personal_identity", "👤 Personal / Identity Investigation"),
    ("corporate_espionage", "🏢 Corporate Espionage / Data Leaks"),
]


def _custom_preset_payload(cp: dict) -> dict:
    return {
        "key": cp["key"],
        "label": f"✨ {cp['name']}",
        "custom": True,
        "description": cp.get("description", ""),
        "system_prompt": cp.get("system_prompt", ""),
        "id": cp["id"],
    }


def _builtin_presets() -> list:
    return [
        {
            "key": key,
            "label": label,
            "custom": False,
            "description": "",
            "system_prompt": PRESET_PROMPTS[key],
        }
        for key, label in _BUILTIN_PRESET_LABELS
    ]


def _build_preset_response() -> list:
    customs = [_custom_preset_payload(cp) for cp in preset_db.list_presets()]
    return _builtin_presets() + customs


# ── Meta ──────────────────────────────────────────────────────────────────

@config_bp.route("/api/version", methods=["GET"])
def api_version():
    return jsonify({"name": "OBSCURA", "version": __version__})


# ── Models ──────────────────────────────────────────────────────────────────

@config_bp.route("/api/models", methods=["GET"])
def api_models():
    models = get_model_choices()
    return jsonify({"models": [{"key": m, "label": m} for m in models]})


# ── Providers ─────────────────────────────────────────────────────────────────

@config_bp.route("/api/providers", methods=["GET"])
def api_providers():
    return jsonify({"providers": env_manager.provider_status()})


@config_bp.route("/api/providers", methods=["POST"])
def api_providers_save():
    data = request.get_json(force=True) or {}
    env_key = (data.get("envKey") or "").strip()
    value = (data.get("value") or "").strip()

    if env_key not in env_manager.allowed_env_keys():
        return jsonify({"error": "Unknown provider env key"}), 400
    if not value:
        return jsonify({"error": "Value cannot be empty"}), 400

    try:
        env_manager.save_provider_value(env_key, value)
    except Exception as exc:
        logging.exception("Failed to save provider key")
        return jsonify({"error": str(exc)}), 500

    return jsonify({"providers": env_manager.provider_status()})


# ── Presets ───────────────────────────────────────────────────────────────────

@config_bp.route("/api/presets", methods=["GET", "POST"])
def api_presets():
    if request.method == "GET":
        return jsonify({"presets": _build_preset_response()})

    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    system_prompt = (data.get("system_prompt") or "").strip()
    description = (data.get("description") or "").strip()
    if not name or not system_prompt:
        return jsonify({"error": "Missing preset name or prompt."}), 400
    try:
        cp = preset_db.create_preset(name, system_prompt, description)
        return jsonify({"preset": _custom_preset_payload(cp)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@config_bp.route("/api/presets/<int:preset_id>", methods=["PUT", "DELETE"])
def api_preset_item(preset_id):
    if request.method == "DELETE":
        preset_db.delete_preset(preset_id)
        return jsonify({"deleted": True})

    data = request.get_json(force=True) or {}
    try:
        cp = preset_db.update_preset(
            preset_id,
            name=data.get("name"),
            system_prompt=data.get("system_prompt"),
            description=data.get("description"),
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    if not cp:
        return jsonify({"error": "Preset not found."}), 404
    return jsonify({"preset": _custom_preset_payload(cp)})


# ── Health ────────────────────────────────────────────────────────────────────

@config_bp.route("/api/health/llm", methods=["POST"])
def api_health_llm():
    data = request.get_json(silent=True) or {}
    model = data.get("model")
    if not model:
        return jsonify({"status": ["Missing model for LLM health check."]}), 400
    result = check_llm_health(model)
    if result["latency_ms"] is not None:
        output = [f"{result['provider']} — {result['status']} ({result['latency_ms']}ms)"]
    else:
        output = [f"{result['provider']} — {result['status']}"]
    if result.get("error"):
        output.append(f"error: {result['error']}")
    return jsonify({"status": output})


@config_bp.route("/api/health/search", methods=["POST"])
def api_health_search():
    tor_result = check_tor_proxy()
    search_results = check_search_engines()
    output = []
    if tor_result["latency_ms"] is not None:
        output.append(f"Tor Proxy — {tor_result['status']} ({tor_result['latency_ms']}ms)")
    else:
        output.append(f"Tor Proxy — {tor_result['status']}")
    if tor_result.get("error"):
        output.append(f"error: {tor_result['error']}")
    for result in search_results:
        if result.get("latency_ms") is not None:
            detail = f"{result['name']} — {result['status']} ({result['latency_ms']}ms)"
        else:
            detail = f"{result['name']} — {result['status']}"
        if result.get("error"):
            detail += f" — {result['error']}"
        output.append(detail)
    return jsonify({"status": output})
