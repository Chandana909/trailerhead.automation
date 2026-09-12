"""
agent/memory/memory_manager.py

Two-tier memory system:
  • Short-term  — in-memory dict (current session)
  • Long-term   — SQLite database (persists across sessions)

Stores:
  • Successful navigation paths
  • UI patterns per Salesforce version / environment
  • Common errors and proven recovery strategies
  • State hash history for loop detection
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import cfg


class MemoryManager:
    """
    Manages short-term (in-memory) and long-term (SQLite) agent memory.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or cfg.MEMORY_DB_PATH
        self._short_term: dict[str, Any] = {}
        self._conn: sqlite3.Connection | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def open(self) -> None:
        """Open (or create) the SQLite database."""
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()

    def __enter__(self) -> "MemoryManager":
        self.open()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ── Short-term memory ─────────────────────────────────────────────────────

    def st_set(self, key: str, value: Any) -> None:
        self._short_term[key] = value

    def st_get(self, key: str, default: Any = None) -> Any:
        return self._short_term.get(key, default)

    def st_clear(self) -> None:
        self._short_term.clear()

    # ── Long-term memory (SQLite) ─────────────────────────────────────────────

    def _create_schema(self) -> None:
        assert self._conn
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS nav_paths (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                environment TEXT NOT NULL,
                from_url    TEXT,
                to_target   TEXT NOT NULL,
                actions     TEXT NOT NULL,  -- JSON array of action dicts
                success     INTEGER NOT NULL DEFAULT 1,
                used_count  INTEGER NOT NULL DEFAULT 1,
                last_used   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ui_patterns (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                environment TEXT NOT NULL,
                pattern_key TEXT NOT NULL UNIQUE,
                selector    TEXT NOT NULL,
                description TEXT,
                validated   INTEGER NOT NULL DEFAULT 1,
                last_seen   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS error_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT,
                action_type     TEXT,
                target          TEXT,
                failure_category TEXT,
                observation     TEXT,
                recovery_strategy TEXT,
                resolved        INTEGER DEFAULT 0,
                timestamp       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recovery_strategies (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                failure_category TEXT NOT NULL,
                strategy        TEXT NOT NULL,  -- JSON
                success_count   INTEGER NOT NULL DEFAULT 0,
                fail_count      INTEGER NOT NULL DEFAULT 0,
                last_used       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS state_hashes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                hash        TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # Navigation paths

    def save_nav_path(
        self,
        environment: str,
        from_url: str,
        to_target: str,
        actions: list[dict],
        success: bool = True,
    ) -> None:
        assert self._conn
        now = datetime.now(timezone.utc).isoformat()
        # Upsert: if the same path exists, increment used_count
        existing = self._conn.execute(
            "SELECT id, used_count FROM nav_paths WHERE environment=? AND to_target=?",
            (environment, to_target),
        ).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE nav_paths SET used_count=?, last_used=?, success=? WHERE id=?",
                (existing["used_count"] + 1, now, int(success), existing["id"]),
            )
        else:
            self._conn.execute(
                "INSERT INTO nav_paths(environment,from_url,to_target,actions,success,last_used) "
                "VALUES(?,?,?,?,?,?)",
                (environment, from_url, to_target, json.dumps(actions), int(success), now),
            )
        self._conn.commit()

    def get_nav_path(self, environment: str, to_target: str) -> list[dict] | None:
        assert self._conn
        row = self._conn.execute(
            "SELECT actions FROM nav_paths WHERE environment=? AND to_target=? AND success=1 "
            "ORDER BY used_count DESC LIMIT 1",
            (environment, to_target),
        ).fetchone()
        if row:
            return json.loads(row["actions"])
        return None

    # UI patterns

    def save_ui_pattern(
        self,
        environment: str,
        pattern_key: str,
        selector: str,
        description: str = "",
        validated: bool = True,
    ) -> None:
        assert self._conn
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO ui_patterns"
            "(environment,pattern_key,selector,description,validated,last_seen) "
            "VALUES(?,?,?,?,?,?)",
            (environment, pattern_key, selector, description, int(validated), now),
        )
        self._conn.commit()

    def get_ui_pattern(self, environment: str, pattern_key: str) -> str | None:
        assert self._conn
        row = self._conn.execute(
            "SELECT selector FROM ui_patterns WHERE environment=? AND pattern_key=? AND validated=1",
            (environment, pattern_key),
        ).fetchone()
        return row["selector"] if row else None

    def invalidate_ui_pattern(self, environment: str, pattern_key: str) -> None:
        """Mark a UI pattern as unvalidated (UI may have changed)."""
        assert self._conn
        self._conn.execute(
            "UPDATE ui_patterns SET validated=0 WHERE environment=? AND pattern_key=?",
            (environment, pattern_key),
        )
        self._conn.commit()

    # Error log

    def log_error(
        self,
        session_id: str,
        action_type: str,
        target: str,
        failure_category: str,
        observation: str,
        recovery_strategy: str | None = None,
    ) -> int:
        assert self._conn
        cur = self._conn.execute(
            "INSERT INTO error_log"
            "(session_id,action_type,target,failure_category,observation,recovery_strategy,timestamp) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                session_id, action_type, target, failure_category,
                observation, recovery_strategy,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
        return cur.lastrowid or 0

    def resolve_error(self, error_id: int) -> None:
        assert self._conn
        self._conn.execute("UPDATE error_log SET resolved=1 WHERE id=?", (error_id,))
        self._conn.commit()

    # Recovery strategies

    def record_recovery(self, failure_category: str, strategy: dict, success: bool) -> None:
        assert self._conn
        now = datetime.now(timezone.utc).isoformat()
        strategy_json = json.dumps(strategy)
        existing = self._conn.execute(
            "SELECT id,success_count,fail_count FROM recovery_strategies "
            "WHERE failure_category=? AND strategy=?",
            (failure_category, strategy_json),
        ).fetchone()
        if existing:
            sc = existing["success_count"] + (1 if success else 0)
            fc = existing["fail_count"] + (0 if success else 1)
            self._conn.execute(
                "UPDATE recovery_strategies SET success_count=?,fail_count=?,last_used=? WHERE id=?",
                (sc, fc, now, existing["id"]),
            )
        else:
            self._conn.execute(
                "INSERT INTO recovery_strategies"
                "(failure_category,strategy,success_count,fail_count,last_used) "
                "VALUES(?,?,?,?,?)",
                (failure_category, strategy_json, int(success), int(not success), now),
            )
        self._conn.commit()

    def best_recovery_strategy(self, failure_category: str) -> dict | None:
        assert self._conn
        row = self._conn.execute(
            "SELECT strategy FROM recovery_strategies "
            "WHERE failure_category=? AND success_count > fail_count "
            "ORDER BY success_count DESC LIMIT 1",
            (failure_category,),
        ).fetchone()
        if row:
            return json.loads(row["strategy"])
        return None

    # State hash (loop detection)

    def record_state_hash(self, session_id: str, hash_val: str) -> None:
        assert self._conn
        self._conn.execute(
            "INSERT INTO state_hashes(session_id,hash,timestamp) VALUES(?,?,?)",
            (session_id, hash_val, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def count_state_hash(self, session_id: str, hash_val: str) -> int:
        assert self._conn
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM state_hashes WHERE session_id=? AND hash=?",
            (session_id, hash_val),
        ).fetchone()
        return row["cnt"] if row else 0
