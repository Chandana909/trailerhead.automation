"""
agent/state.py

AgentState — the single source of truth for the entire autonomous agent session.
Serializable to/from JSON for persistence and recovery.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class WorkflowStatus(str, Enum):
    DISCOVER   = "DISCOVER"
    UNDERSTAND = "UNDERSTAND"
    RESEARCH   = "RESEARCH"
    PLAN       = "PLAN"
    EXECUTE    = "EXECUTE"
    VERIFY     = "VERIFY"
    RECOVER    = "RECOVER"
    COMPLETE   = "COMPLETE"
    FAILED     = "FAILED"


class FailureCategory(str, Enum):
    ELEMENT_NOT_FOUND   = "ELEMENT_NOT_FOUND"
    PAGE_CHANGED        = "PAGE_CHANGED"
    VALIDATION_ERROR    = "VALIDATION_ERROR"
    PERMISSION_ERROR    = "PERMISSION_ERROR"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    TIMEOUT             = "TIMEOUT"
    STALE_STATE         = "STALE_STATE"
    AMBIGUOUS_ELEMENT   = "AMBIGUOUS_ELEMENT"
    UNEXPECTED_DIALOG   = "UNEXPECTED_DIALOG"
    UNKNOWN             = "UNKNOWN"


@dataclass
class ActionRecord:
    """A single executed action and its observation."""
    action_type: str              # navigate | click | type | select | ...
    target: str
    value: str | None = None
    observation: str = ""
    result: str = "pending"       # success | failure | partial
    failure_category: str | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class VerificationRecord:
    """Result of a post-action state verification."""
    success: bool
    evidence: list[str] = field(default_factory=list)
    discrepancies: list[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class AgentState:
    """
    Persistent state for one autonomous agent session.

    This is the memory spine of the entire system — every component reads
    from and writes to a shared AgentState instance.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ── Browser position ──────────────────────────────────────────────────────
    current_url: str = ""
    current_page: str = ""         # human-readable page name

    # ── Salesforce workflow position ──────────────────────────────────────────
    current_module: str = ""
    current_unit: str = ""
    current_task: str = ""

    # ── Rich context bags ─────────────────────────────────────────────────────
    task_context: dict[str, Any] = field(default_factory=dict)
    research_context: list[dict] = field(default_factory=list)
    action_plan: list[dict] = field(default_factory=list)   # pending actions

    # ── History ───────────────────────────────────────────────────────────────
    completed_actions: list[ActionRecord] = field(default_factory=list)
    failed_actions: list[ActionRecord] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    verification_results: list[VerificationRecord] = field(default_factory=list)

    # ── Retry / recovery ─────────────────────────────────────────────────────
    retry_count: int = 0
    last_failure: str | None = None

    # ── State machine ─────────────────────────────────────────────────────────
    workflow_status: WorkflowStatus = WorkflowStatus.DISCOVER

    # ── Loop detection ────────────────────────────────────────────────────────
    state_hash: str = ""
    state_hash_history: list[str] = field(default_factory=list)
    loop_detected: bool = False

    # ── Task completion ───────────────────────────────────────────────────────
    tasks_completed: list[str] = field(default_factory=list)
    tasks_failed: list[str] = field(default_factory=list)

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def compute_hash(self, extra: str = "") -> str:
        """
        Compute a state hash from the current URL + pending action plan +
        current task. Used to detect loops.
        """
        raw = f"{self.current_url}|{self.current_task}|{json.dumps(self.action_plan)}|{extra}"
        self.state_hash = hashlib.md5(raw.encode()).hexdigest()
        return self.state_hash

    def check_loop(self) -> bool:
        """Return True if the current state hash has appeared before."""
        h = self.state_hash
        if h and self.state_hash_history.count(h) >= 2:
            self.loop_detected = True
            return True
        if h:
            self.state_hash_history.append(h)
        return False

    def transition(self, status: WorkflowStatus) -> None:
        self.workflow_status = status

    def record_observation(self, obs: str) -> None:
        self.observations.append(obs)
        # Keep last 50 observations in memory
        if len(self.observations) > 50:
            self.observations = self.observations[-50:]

    def record_action(self, action: ActionRecord) -> None:
        if action.result == "success":
            self.completed_actions.append(action)
            self.retry_count = 0
        else:
            self.failed_actions.append(action)
            self.retry_count += 1
            self.last_failure = action.observation

    def record_verification(self, result: VerificationRecord) -> None:
        self.verification_results.append(result)

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        d = asdict(self)
        d["workflow_status"] = self.workflow_status.value
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def save(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_dict(cls, d: dict) -> "AgentState":
        d = dict(d)
        d["workflow_status"] = WorkflowStatus(d.get("workflow_status", "DISCOVER"))
        # Re-hydrate nested dataclasses
        d["completed_actions"] = [ActionRecord(**a) for a in d.get("completed_actions", [])]
        d["failed_actions"] = [ActionRecord(**a) for a in d.get("failed_actions", [])]
        d["verification_results"] = [VerificationRecord(**v) for v in d.get("verification_results", [])]
        return cls(**d)

    @classmethod
    def load(cls, path: Path) -> "AgentState":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
