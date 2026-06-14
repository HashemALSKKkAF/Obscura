# obscura_config.py — configuration for OBSCURA.
#
# Loads API keys and Tor settings from the environment / .env. Tor SOCKS and
# control ports are *probed lazily and cached* (get_socks_port/get_control_port)
# instead of at import time, so importing this module has no network side effect
# and it stays cheap to import in tests.
import functools
import os
import socket

from dotenv import load_dotenv

load_dotenv()

DEFAULT_SOCKS_PORT = 9150
DEFAULT_CONTROL_PORT = 9151


def _clean_env(name, default=None):
    value = os.getenv(name, default)
    if value is None:
        return None
    value = str(value).strip()
    # Support accidentally quoted values copied into .env
    if len(value) >= 2 and (
        (value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")
    ):
        value = value[1:-1].strip()
    return value


def _probe_port(candidates, env_name, fallback):
    """Return an explicit env port if set, else the first reachable candidate,
    else the fallback default."""
    env_port = _clean_env(env_name)
    if env_port:
        return int(env_port)
    for port in candidates:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return port
        except Exception:
            continue
    return fallback


@functools.lru_cache(maxsize=1)
def get_socks_port() -> int:
    """Reachable Tor SOCKS5 port (9150 or 9050), cached after first probe."""
    return _probe_port([9150, 9050], "TOR_SOCKS_PORT", DEFAULT_SOCKS_PORT)


@functools.lru_cache(maxsize=1)
def get_control_port() -> int:
    """Reachable Tor control port (9151 or 9051), cached after first probe."""
    return _probe_port([9151, 9051], "TOR_CONTROL_PORT", DEFAULT_CONTROL_PORT)


# API keys / endpoints are read LIVE (not snapshotted at import) so a value
# saved at runtime — e.g. a key entered in the UI, which writes os.environ —
# takes effect immediately without reloading modules.
def openai_api_key():
    return _clean_env("OPENAI_API_KEY")


def google_api_key():
    return _clean_env("GOOGLE_API_KEY")


def anthropic_api_key():
    return _clean_env("ANTHROPIC_API_KEY")


def ollama_base_url():
    return _clean_env("OLLAMA_BASE_URL")


def openrouter_base_url():
    return _clean_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")


def openrouter_api_key():
    return _clean_env("OPENROUTER_API_KEY")


def llama_cpp_base_url():
    return _clean_env("LLAMA_CPP_BASE_URL")
