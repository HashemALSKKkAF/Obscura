"""
env_manager.py
Runtime configuration surface for the settings UI.

Two responsibilities pulled out of the old app.py god-module:
  - :class:`EnvFileManager` — read/modify/write the on-disk .env, preserving
    comments and ordering (used when the UI saves a provider key/URL).
  - :func:`provider_status` — the provider list the settings panel renders,
    derived entirely from the provider registry (no parallel env map).

Because providers read their credentials live (see providers.py), saving a key
just needs os.environ + the .env file updated — no module reloading.
"""
import os
from pathlib import Path

import providers

ENV_FILE_PATH = Path(__file__).resolve().parent / ".env"


class EnvFileManager:
    """Idempotent .env writer that preserves comments and key order."""

    def __init__(self, path: Path = ENV_FILE_PATH):
        self.path = Path(path)

    def upsert(self, env_key: str, new_value: str) -> None:
        """Set ``env_key=new_value`` in the .env file.

        If the key already exists (commented or not) that line is replaced;
        otherwise it's appended. Other lines/comments are left intact.
        """
        if self.path.exists():
            lines = self.path.read_text(encoding="utf-8").splitlines()
        else:
            lines = []

        new_line = f"{env_key}={new_value}"
        replaced = False
        for i, raw in enumerate(lines):
            stripped = raw.lstrip()
            # Match both "KEY=..." and "# KEY=..."
            candidate = stripped[1:].lstrip() if stripped.startswith("#") else stripped
            if candidate.startswith(env_key + "=") or candidate.startswith(env_key + " ="):
                lines[i] = new_line
                replaced = True
                break
        if not replaced:
            if lines and lines[-1].strip() != "":
                lines.append("")
            lines.append(new_line)

        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_provider_value(env_key: str, value: str) -> None:
    """Persist a provider credential to .env and the live environment."""
    EnvFileManager().upsert(env_key, value)
    os.environ[env_key] = value


def provider_status() -> list:
    """Status of every known provider for the settings panel (registry-driven)."""
    out = []
    for provider in providers.PROVIDERS:
        configured = provider.is_configured()
        entry = {
            "name": provider.name,
            "envKey": provider.env_var,
            "fieldKind": provider.field_kind,
            "isCloud": provider.is_cloud,
            "hasValue": configured,
        }
        if configured:
            entry.update({
                "message": "configured",
                "statusLabel": "configured",
                "statusLevel": "success",
            })
        elif provider.is_cloud:
            entry.update({
                "message": "API key not set",
                "statusLabel": "not set",
                "statusLevel": "warning",
            })
        else:
            entry.update({
                "message": "not configured (optional)",
                "statusLabel": "optional",
                "statusLevel": "neutral",
            })
        out.append(entry)
    return out


def allowed_env_keys() -> set:
    """Env var names the UI is permitted to write (the configured providers)."""
    return {p.env_var for p in providers.PROVIDERS}
