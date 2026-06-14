"""
db.py
Shared SQLite connection layer for OBSCURA's persistence modules.

Previously investigations.py, seeds.py and presets.py each carried an
identical private ``_connect()`` (same path, same PRAGMAs, same row factory).
That duplication is consolidated here so there is one place that decides
*where* the database lives and *how* a connection is configured.

  - ``DB_PATH``  — the single source of truth for the database location.
  - ``connect()`` — returns a configured ``sqlite3.Connection``.
  - ``BaseRepository`` — base class the entity repositories extend; it owns the
    ``connect()`` access so subclasses depend on this abstraction (DIP) rather
    than re-implementing connection handling.
"""
import sqlite3
from pathlib import Path

# Single source of truth for the database file. Tests redirect this via
# monkeypatch; production keeps the historical investigations/obscura.db path.
DB_PATH = Path("investigations") / "obscura.db"


def connect(db_path: "Path | str | None" = None) -> sqlite3.Connection:
    """Open a configured connection.

    Args:
        db_path: Override the target file. Defaults to the module-level
            ``DB_PATH`` (looked up at call time so monkeypatching works).

    The connection uses ``Row`` for dict-like access, WAL journaling for
    concurrent reads, and enforced foreign keys.
    """
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class BaseRepository:
    """Base class for SQLite-backed entity repositories.

    Subclasses get connection handling for free and implement their own schema
    bootstrap + queries. Keeping ``connect`` here means the connection policy
    (path, PRAGMAs) lives in exactly one place.
    """

    def connect(self) -> sqlite3.Connection:
        return connect()

    @staticmethod
    def row_to_dict(row: "sqlite3.Row | None") -> "dict | None":
        return dict(row) if row is not None else None
