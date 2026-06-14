"""
seeds.py
Seed URL management for OBSCURA's Deep Crawl feature.

Seeds live in the shared SQLite DB (see db.py) in a dedicated ``seeds`` table.
Exposed as a :class:`SeedRepository` plus backward-compatible module functions.

Schema
------
seeds
  id          INTEGER PRIMARY KEY AUTOINCREMENT
  url         TEXT UNIQUE NOT NULL
  hash        TEXT NOT NULL            -- SHA-256 of the URL
  name        TEXT NOT NULL DEFAULT '' -- human label
  status_code INTEGER                  -- last HTTP response code (nullable)
  crawled     INTEGER NOT NULL DEFAULT 0   -- 0/1 bool
  loaded      INTEGER NOT NULL DEFAULT 0   -- 0/1 bool (deep content extracted)
  content     TEXT    NOT NULL DEFAULT '' -- extracted plain-text content
  crawled_at  TEXT                        -- ISO-8601 of last crawl
  added_at    TEXT    NOT NULL            -- ISO-8601 timestamp
"""

import hashlib
import logging
import sqlite3
from datetime import datetime

import db

_logger = logging.getLogger(__name__)


class SeedRepository(db.BaseRepository):
    """SQLite-backed store for deep-crawl seed URLs."""

    def init_table(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS seeds (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    url         TEXT    UNIQUE NOT NULL,
                    hash        TEXT    NOT NULL,
                    name        TEXT    NOT NULL DEFAULT '',
                    status_code INTEGER,
                    crawled     INTEGER NOT NULL DEFAULT 0,
                    loaded      INTEGER NOT NULL DEFAULT 0,
                    content     TEXT    NOT NULL DEFAULT '',
                    crawled_at  TEXT,
                    added_at    TEXT    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_seeds_crawled ON seeds(crawled);
                CREATE INDEX IF NOT EXISTS idx_seeds_loaded  ON seeds(loaded);
            """)
            # Idempotent migration for older DBs that pre-date content/crawled_at.
            existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(seeds)")}
            if "content" not in existing_cols:
                conn.execute("ALTER TABLE seeds ADD COLUMN content TEXT NOT NULL DEFAULT ''")
            if "crawled_at" not in existing_cols:
                conn.execute("ALTER TABLE seeds ADD COLUMN crawled_at TEXT")

    @staticmethod
    def _sha256(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    # -- write --------------------------------------------------------------

    def add(self, url: str, name: str = "") -> dict:
        """Add a new seed URL. Returns the seed dict. Idempotent on URL."""
        self.init_table()
        url = url.strip().rstrip("/")
        if not url:
            raise ValueError("URL cannot be empty.")

        ts = datetime.now().isoformat()
        with self.connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO seeds (url, hash, name, added_at) VALUES (?, ?, ?, ?)",
                    (url, self._sha256(url), name.strip() or "unknown", ts),
                )
            except sqlite3.IntegrityError:
                pass  # already exists — fall through and return existing row
        return self.get_by_url(url)

    def mark_crawled(self, seed_id: int, status_code: int = None, content: str = "") -> None:
        """Mark a seed crawled; persisting content also flags it loaded."""
        ts = datetime.now().isoformat()
        with self.connect() as conn:
            if content:
                conn.execute(
                    """UPDATE seeds
                          SET crawled=1, loaded=1, status_code=?, content=?, crawled_at=?
                        WHERE id=?""",
                    (status_code, content, ts, seed_id),
                )
            else:
                conn.execute(
                    "UPDATE seeds SET crawled=1, status_code=?, crawled_at=? WHERE id=?",
                    (status_code, ts, seed_id),
                )

    def delete(self, seed_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM seeds WHERE id=?", (seed_id,))

    # -- read ---------------------------------------------------------------

    def get_by_url(self, url: str) -> "dict | None":
        self.init_table()
        url = url.strip().rstrip("/")
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM seeds WHERE url=?", (url,)).fetchone()
            return self.row_to_dict(row)

    def get_all(self) -> list:
        self.init_table()
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM seeds ORDER BY added_at DESC").fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Backward-compatible module-level API.
# ---------------------------------------------------------------------------

_repo = SeedRepository()


def init_seeds_table() -> None:
    _repo.init_table()


def add_seed(url: str, name: str = "") -> dict:
    return _repo.add(url, name)


def mark_crawled(seed_id: int, status_code: int = None, content: str = "") -> None:
    _repo.mark_crawled(seed_id, status_code, content)


def delete_seed(seed_id: int) -> None:
    _repo.delete(seed_id)


def get_seed_by_url(url: str) -> dict:
    return _repo.get_by_url(url)


def get_all_seeds() -> list:
    return _repo.get_all()
