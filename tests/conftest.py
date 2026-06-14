"""Shared pytest fixtures for the OBSCURA characterization suite.

These tests pin *current* behavior so the SOLID/OOP refactor can be verified
to preserve it. Nothing here touches the network or a real Tor daemon.
"""
import sys
from pathlib import Path

import pytest

# tests/ lives inside the app package dir; make the modules importable
# regardless of the working directory pytest is launched from.
APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Redirect the shared DB location at one throwaway SQLite file.

    All three repositories share db.DB_PATH (as in production), so redirecting
    it once keeps the real investigations/obscura.db untouched.
    """
    import db as db_module
    import investigations

    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_file)
    # init_db() globs LEGACY_DIR for legacy-JSON migration — point it at an
    # empty temp dir so it's a guaranteed no-op.
    monkeypatch.setattr(investigations, "LEGACY_DIR", tmp_path)
    return db_file


# A valid v3 onion host (Ahmia's), reused across search-parser tests.
ONION_HOST = "juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd"
ONION_URL = f"http://{ONION_HOST}.onion"
