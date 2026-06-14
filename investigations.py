"""
investigations.py
Persistent SQLite storage for OBSCURA investigations.

Connection handling now lives in db.py (shared by seeds.py / presets.py); this
module owns only the investigations + sources schema and queries, exposed both
as an :class:`InvestigationRepository` (OOP entry point) and as backward-
compatible module-level functions that delegate to a shared instance.

Schema
------
investigations
  id            INTEGER PRIMARY KEY AUTOINCREMENT
  timestamp     TEXT    ISO-8601 creation time
  query         TEXT    original user query
  refined_query TEXT    LLM-refined query
  model         TEXT    model used
  preset        TEXT    preset label
  summary       TEXT    full markdown summary
  status        TEXT    "active" | "pending" | "closed" | "complete"
  tags          TEXT    comma-separated tags

sources
  id                INTEGER PRIMARY KEY AUTOINCREMENT
  investigation_id  INTEGER → investigations(id) ON DELETE CASCADE
  title             TEXT
  link              TEXT
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import db

LEGACY_DIR = Path("investigations")
VALID_STATUSES = ("active", "pending", "closed", "complete")

_logger = logging.getLogger(__name__)


class InvestigationRepository(db.BaseRepository):
    """SQLite-backed store for investigations and their source links."""

    # -- schema + migration -------------------------------------------------

    def init_db(self) -> None:
        """Create tables if absent, then migrate any legacy JSON files."""
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS investigations (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp     TEXT NOT NULL,
                    query         TEXT NOT NULL,
                    refined_query TEXT NOT NULL DEFAULT '',
                    model         TEXT NOT NULL DEFAULT '',
                    preset        TEXT NOT NULL DEFAULT '',
                    summary       TEXT NOT NULL DEFAULT '',
                    status        TEXT NOT NULL DEFAULT 'active',
                    tags          TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS sources (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    investigation_id  INTEGER NOT NULL
                                      REFERENCES investigations(id) ON DELETE CASCADE,
                    title             TEXT NOT NULL DEFAULT '',
                    link              TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_inv_timestamp ON investigations(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_inv_status    ON investigations(status);
            """)
        self._migrate_legacy_json()

    def _migrate_legacy_json(self) -> None:
        """Import existing investigation_*.json files into SQLite, then delete them."""
        json_files = sorted(LEGACY_DIR.glob("investigation_*.json"))
        if not json_files:
            return
        migrated = 0
        for path in json_files:
            try:
                data = json.loads(path.read_text())
                self.save(
                    query=data.get("query", ""),
                    refined_query=data.get("refined_query", ""),
                    model=data.get("model", ""),
                    preset_label=data.get("preset", ""),
                    sources=data.get("sources", []),
                    summary=data.get("summary", ""),
                    timestamp=data.get("timestamp"),
                )
                path.unlink()
                migrated += 1
            except Exception as exc:
                _logger.warning("Failed to migrate %s: %s", path.name, exc)
        if migrated:
            _logger.info("Migrated %d legacy JSON investigation(s) to SQLite.", migrated)

    # -- write --------------------------------------------------------------

    def save(
        self,
        query: str,
        refined_query: str,
        model: str,
        preset_label: str,
        sources: list,
        summary: str,
        status: str = "active",
        tags: str = "",
        timestamp: "str | None" = None,
    ) -> int:
        """Save an investigation. Returns the new row id."""
        ts = timestamp or datetime.now().isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO investigations
                   (timestamp, query, refined_query, model, preset, summary, status, tags)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, query, refined_query, model, preset_label, summary, status, tags.strip()),
            )
            inv_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO sources (investigation_id, title, link) VALUES (?, ?, ?)",
                [(inv_id, s.get("title", ""), s.get("link", "")) for s in sources],
            )
        return inv_id

    def update_status(self, inv_id: int, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Choose from {VALID_STATUSES}.")
        with self.connect() as conn:
            conn.execute("UPDATE investigations SET status=? WHERE id=?", (status, inv_id))

    def update_tags(self, inv_id: int, tags: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE investigations SET tags=? WHERE id=?", (tags.strip(), inv_id))

    def update_summary(
        self,
        inv_id: int,
        summary: str,
        refined_query: "str | None" = None,
        model: "str | None" = None,
        preset_label: "str | None" = None,
    ) -> None:
        """Update the summary (and optionally other metadata) for an investigation."""
        with self.connect() as conn:
            if refined_query is not None:
                conn.execute(
                    "UPDATE investigations SET summary=?, refined_query=?, model=?, preset=? WHERE id=?",
                    (summary, refined_query, model or '', preset_label or '', inv_id),
                )
            else:
                conn.execute(
                    "UPDATE investigations SET summary=? WHERE id=?", (summary, inv_id)
                )

    def delete(self, inv_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM investigations WHERE id=?", (inv_id,))

    # -- read ---------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row, sources: list) -> dict:
        d = dict(row)
        d["sources"] = sources
        d["tags_list"] = [t.strip() for t in d.get("tags", "").split(",") if t.strip()]
        return d

    def load_all(
        self,
        status_filter: "str | None" = None,
        tag_filter: "str | None" = None,
        limit: int = 200,
    ) -> list:
        """Return investigations newest-first, with optional status/tag filters."""
        self.init_db()
        clauses, params = [], []
        if status_filter:
            clauses.append("status = ?")
            params.append(status_filter)
        if tag_filter:
            clauses.append("LOWER(tags) LIKE ?")
            params.append(f"%{tag_filter.lower()}%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM investigations {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
            results = []
            for row in rows:
                srcs = conn.execute(
                    "SELECT title, link FROM sources WHERE investigation_id=?", (row["id"],)
                ).fetchall()
                results.append(self._row_to_dict(row, [dict(s) for s in srcs]))
        return results

    def load_one(self, inv_id: int) -> "dict | None":
        """Load a single investigation by id. Returns None if not found."""
        self.init_db()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM investigations WHERE id=?", (inv_id,)
            ).fetchone()
            if not row:
                return None
            srcs = conn.execute(
                "SELECT title, link FROM sources WHERE investigation_id=?", (inv_id,)
            ).fetchall()
            return self._row_to_dict(row, [dict(s) for s in srcs])

    def get_all_tags(self) -> list:
        """Return a sorted deduplicated list of every tag across all investigations."""
        self.init_db()
        with self.connect() as conn:
            rows = conn.execute("SELECT tags FROM investigations WHERE tags != ''").fetchall()
        tags = set()
        for row in rows:
            for t in row["tags"].split(","):
                t = t.strip()
                if t:
                    tags.add(t)
        return sorted(tags)


# ---------------------------------------------------------------------------
# Backward-compatible module-level API (delegates to a shared repository).
# ---------------------------------------------------------------------------

_repo = InvestigationRepository()


def init_db() -> None:
    _repo.init_db()


def save_investigation(
    query: str,
    refined_query: str,
    model: str,
    preset_label: str,
    sources: list,
    summary: str,
    status: str = "active",
    tags: str = "",
    timestamp: str = None,
) -> int:
    return _repo.save(
        query, refined_query, model, preset_label, sources, summary, status, tags, timestamp
    )


def update_status(inv_id: int, status: str) -> None:
    _repo.update_status(inv_id, status)


def update_tags(inv_id: int, tags: str) -> None:
    _repo.update_tags(inv_id, tags)


def update_summary(inv_id, summary, refined_query=None, model=None, preset_label=None) -> None:
    _repo.update_summary(inv_id, summary, refined_query, model, preset_label)


def delete_investigation(inv_id: int) -> None:
    _repo.delete(inv_id)


def load_all(status_filter: str = None, tag_filter: str = None, limit: int = 200) -> list:
    return _repo.load_all(status_filter, tag_filter, limit)


def load_one(inv_id: int) -> dict:
    return _repo.load_one(inv_id)


def get_all_tags() -> list:
    return _repo.get_all_tags()
