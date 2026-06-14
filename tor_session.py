"""
tor_session.py
Single source of truth for OBSCURA's HTTP sessions.

Previously scrape.py and search.py each carried their own (slightly different)
``get_tor_session`` / ``_build_session`` with duplicated Retry + SOCKS-proxy
wiring. This module unifies them so every component (scrape, search, crawler,
health) shares one configuration and the Tor SOCKS port is resolved live from
obscura_config at build time.

  - ``get_session(use_tor=True)`` — thread-local cached session (hot scrape path).
  - ``get_tor_session()`` — a fresh Tor session (used by per-request callers).
"""
import threading

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import obscura_config

_thread_local = threading.local()


def _build_session(use_tor: bool = True, retries: int = 3) -> requests.Session:
    """Create a requests Session with retries (and, optionally, the Tor proxy).

    ``retries`` is configurable because the right value depends on the caller:
    scraping a chosen source wants resilience (retry transient onion failures),
    but *search* aggregation is best-effort fan-out across many engines — there,
    retrying a dead engine 3× at a 40s timeout costs ~160s for nothing, so
    callers pass ``retries=0`` to fail fast and move on.
    """
    session = requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=0.3,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "HEAD"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    if use_tor:
        port = obscura_config.get_socks_port()
        session.proxies = {
            "http": f"socks5h://127.0.0.1:{port}",
            "https": f"socks5h://127.0.0.1:{port}",
        }
    return session


def get_session(use_tor: bool = True) -> requests.Session:
    """Return a thread-local cached session (one per thread per use_tor flag)."""
    key = "tor_session" if use_tor else "direct_session"
    if not hasattr(_thread_local, key):
        setattr(_thread_local, key, _build_session(use_tor=use_tor))
    return getattr(_thread_local, key)


def get_tor_session(retries: int = 3) -> requests.Session:
    """Return a fresh Tor SOCKS5 session. Pass ``retries=0`` for best-effort,
    fail-fast callers (e.g. search-engine fan-out)."""
    return _build_session(use_tor=True, retries=retries)
