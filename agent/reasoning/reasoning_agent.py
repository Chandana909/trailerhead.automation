"""
agent/reasoning/reasoning_agent.py

LLM Reasoning Agent — sends context to Groq (llama-3.3-70b-versatile)
and returns a validated ActionPlan.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential

from config import cfg
from agent.state import AgentState
from agent.perception.page_model import PageState
from agent.reasoning.prompts import SYSTEM_PROMPT, build_user_prompt


# ─────────────────────────────────────────────────────────────────────────────
# Output models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlannedAction:
    id: int
    action: str           # navigate | click | type | select | check | ...
    target: str
    value: str | None = None
    reason: str = ""
    expected_result: str = ""


@dataclass
class ActionPlan:
    goal: str
    confidence: float
    reasoning_steps: list[dict[str, str]] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    actions: list[PlannedAction] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    destructive: bool = False
    requires_human_confirmation: bool = False
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "confidence": self.confidence,
            "reasoning_steps": self.reasoning_steps,
            "preconditions": self.preconditions,
            "actions": [
                {
                    "id": a.id,
                    "action": a.action,
                    "target": a.target,
                    "value": a.value,
                    "reason": a.reason,
                    "expected_result": a.expected_result,
                }
                for a in self.actions
            ],
            "verification": self.verification,
            "destructive": self.destructive,
            "requires_human_confirmation": self.requires_human_confirmation,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Reasoning agent
# ─────────────────────────────────────────────────────────────────────────────

class ReasoningAgent:
    """
    Sends the current agent context to the Groq LLM and returns a validated
    ActionPlan. Retries on transient errors.
    """

    def __init__(self) -> None:
        self._client = Groq(api_key=cfg.GROQ_API_KEY)

    def plan(self, page: PageState, state: AgentState) -> ActionPlan:
        """
        Synchronous entry point.
        Build the prompt → call LLM → parse → validate → return ActionPlan.
        """
        user_prompt = build_user_prompt(
            page_summary=page.summary(),
            task_context=state.task_context,
            research_context=state.research_context,
            completed_actions=[
                {
                    "action_type": a.action_type,
                    "target": a.target,
                    "result": a.result,
                    "observation": a.observation,
                }
                for a in state.completed_actions[-10:]
            ],
            failed_actions=[
                {
                    "action_type": a.action_type,
                    "target": a.target,
                    "observation": a.observation,
                }
                for a in state.failed_actions[-5:]
            ],
            retry_count=state.retry_count,
            last_failure=state.last_failure,
        )

        raw = self._call_llm(user_prompt)
        plan = self._parse_plan(raw)
        self._validate_plan(plan)
        return plan

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _call_llm(self, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=cfg.GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,     # Low temperature for deterministic structured output
            max_tokens=2048,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    def _parse_plan(self, raw: str) -> ActionPlan:
        """Parse LLM JSON output into a typed ActionPlan."""
        # Strip any accidental markdown fences
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        try:
            data: dict = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM returned invalid JSON: {e}\n---\n{cleaned[:500]}") from e

        actions = [
            PlannedAction(
                id=a.get("id", i + 1),
                action=a.get("action", "read_page"),
                target=a.get("target", ""),
                value=a.get("value"),
                reason=a.get("reason", ""),
                expected_result=a.get("expected_result", ""),
            )
            for i, a in enumerate(data.get("actions", []))
        ]

        return ActionPlan(
            goal=data.get("goal", ""),
            confidence=float(data.get("confidence", 0.5)),
            reasoning_steps=data.get("reasoning_steps", []),
            preconditions=data.get("preconditions", []),
            actions=actions,
            verification=data.get("verification", []),
            destructive=bool(data.get("destructive", False)),
            requires_human_confirmation=bool(data.get("requires_human_confirmation", False)),
            raw_response=raw,
        )

    def _validate_plan(self, plan: ActionPlan) -> None:
        """Raise ValueError if the plan violates safety rules."""
        if len(plan.actions) > 15:
            # Truncate to avoid runaway execution
            plan.actions = plan.actions[:15]

        for action in plan.actions:
            if action.action not in {
                "navigate", "click", "type", "select", "check", "uncheck",
                "scroll", "wait", "go_back", "read_page", "find_element",
                "switch_tab", "switch_window",
            }:
                raise ValueError(f"Unknown action type: {action.action!r}")

            # Destructive actions must have human confirmation
            if action.action in {"delete_record", "delete_field", "delete_object"}:
                plan.destructive = True
                plan.requires_human_confirmation = True
