"""
observability/logger.py

Machine-readable JSON Lines logger.
Every agent event is written as a single JSON object per line.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import cfg


class AgentLogger:
    """Writes structured JSONL logs to disk."""

    def __init__(self, session_id: str) -> None:
        cfg.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._path = cfg.LOG_DIR / f"agent_log_{session_id}.jsonl"
        self._fh = self._path.open("a", encoding="utf-8")

        # Also configure Python's standard logging for library noise
        logging.basicConfig(
            level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
            format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        )
        self._log = logging.getLogger("agent")

    def log(
        self,
        state: str,
        action: str = "",
        observation: str = "",
        result: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "state": state,
        }
        if action:
            record["action"] = action
        if observation:
            record["observation"] = observation[:500]
        if result:
            record["result"] = result
        if extra:
            record.update(extra)

        line = json.dumps(record, default=str)
        self._fh.write(line + "\n")
        self._fh.flush()

        level = logging.ERROR if result == "failure" else logging.INFO
        self._log.log(level, "[%s] %s %s", state, action or "", observation[:120] if observation else "")

    def close(self) -> None:
        self._fh.close()

    @property
    def log_path(self) -> Path:
        return self._path
