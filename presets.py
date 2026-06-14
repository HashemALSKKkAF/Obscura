"""
presets.py
Persistent storage for user-defined research-domain presets.

The four built-in presets (threat_intel, ransomware_malware,
personal_identity, corporate_espionage) live in ``llm.PRESET_PROMPTS`` and are
NEVER touched here — this module only manages user-created domains, exposed as
a :class:`PresetRepository` plus backward-compatible module functions.

Schema
------
custom_presets
  id            INTEGER PRIMARY KEY AUTOINCREMENT
  name          TEXT UNIQUE NOT NULL    -- human label, e.g. "Crypto Tracing"
  description   TEXT NOT NULL DEFAULT ''
  system_prompt TEXT NOT NULL           -- full system prompt template
  created_at    TEXT NOT NULL
  updated_at    TEXT NOT NULL
"""

import logging
import sqlite3
from datetime import datetime

import db

_logger = logging.getLogger(__name__)

# Prefix used to disambiguate a custom-preset key from a built-in one
# everywhere keys are passed around as strings.
CUSTOM_KEY_PREFIX = "custom:"


def is_custom_key(preset_key: str) -> bool:
    return isinstance(preset_key, str) and preset_key.startswith(CUSTOM_KEY_PREFIX)


class PresetRepository(db.BaseRepository):
    """SQLite-backed store for user-defined domain presets."""

    def init_table(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS custom_presets (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT    UNIQUE NOT NULL,
                    description   TEXT    NOT NULL DEFAULT '',
                    system_prompt TEXT    NOT NULL,
                    created_at    TEXT    NOT NULL,
                    updated_at    TEXT    NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_custom_presets_name
                    ON custom_presets(name);
            """)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        # The string key the UI uses to identify this preset everywhere.
        d["key"] = f"{CUSTOM_KEY_PREFIX}{d['id']}"
        return d

    # -- read ---------------------------------------------------------------

    def list(self) -> list:
        self.init_table()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM custom_presets ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get(self, preset_id: int) -> "dict | None":
        self.init_table()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM custom_presets WHERE id=?", (preset_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    # -- write --------------------------------------------------------------

    def create(self, name: str, system_prompt: str, description: str = "") -> dict:
        """Insert a new custom preset. Raises ValueError on conflict/empty input."""
        self.init_table()
        name = (name or "").strip()
        system_prompt = (system_prompt or "").strip()
        description = (description or "").strip()

        if not name:
            raise ValueError("Preset name cannot be empty.")
        if not system_prompt:
            raise ValueError("System prompt cannot be empty.")

        ts = datetime.now().isoformat()
        with self.connect() as conn:
            try:
                cur = conn.execute(
                    """INSERT INTO custom_presets
                       (name, description, system_prompt, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (name, description, system_prompt, ts, ts),
                )
                preset_id = cur.lastrowid
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"A custom preset named '{name}' already exists.") from exc
        return self.get(preset_id)

    def update(
        self,
        preset_id: int,
        name: "str | None" = None,
        system_prompt: "str | None" = None,
        description: "str | None" = None,
    ) -> "dict | None":
        """Partial update — only non-None fields are written."""
        self.init_table()
        sets, params = [], []
        if name is not None:
            n = name.strip()
            if not n:
                raise ValueError("Preset name cannot be empty.")
            sets.append("name=?")
            params.append(n)
        if system_prompt is not None:
            sp = system_prompt.strip()
            if not sp:
                raise ValueError("System prompt cannot be empty.")
            sets.append("system_prompt=?")
            params.append(sp)
        if description is not None:
            sets.append("description=?")
            params.append(description.strip())

        if not sets:
            return self.get(preset_id)

        sets.append("updated_at=?")
        params.append(datetime.now().isoformat())
        params.append(preset_id)

        with self.connect() as conn:
            try:
                conn.execute(
                    f"UPDATE custom_presets SET {', '.join(sets)} WHERE id=?", params
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Another preset already uses that name.") from exc
        return self.get(preset_id)

    def delete(self, preset_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM custom_presets WHERE id=?", (preset_id,))


# ---------------------------------------------------------------------------
# Backward-compatible module-level API.
# ---------------------------------------------------------------------------

_repo = PresetRepository()


def init_presets_table() -> None:
    _repo.init_table()


def list_presets() -> list:
    return _repo.list()


def get_preset(preset_id: int) -> "dict | None":
    return _repo.get(preset_id)


def create_preset(name: str, system_prompt: str, description: str = "") -> dict:
    return _repo.create(name, system_prompt, description)


def update_preset(preset_id, name=None, system_prompt=None, description=None) -> "dict | None":
    return _repo.update(preset_id, name, system_prompt, description)


def delete_preset(preset_id: int) -> None:
    _repo.delete(preset_id)
