"""
agent/recovery/recovery_agent.py

Recovery Agent — classifies failures, determines whether state is safe
to retry, re-plans with failure context, and applies bounded retries.

Failure categories (from state.py):
  ELEMENT_NOT_FOUND | PAGE_CHANGED | VALIDATION_ERROR | PERMISSION_ERROR |
  AUTHENTICATION_ERROR | TIMEOUT | STALE_STATE | AMBIGUOUS_ELEMENT |
  UNEXPECTED_DIALOG | UNKNOWN
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agent.actions.action_agent import ActionObservation
from agent.perception.page_model import PageState
from agent.state import AgentState, FailureCategory, WorkflowStatus


@dataclass
class RecoveryPlan:
    """Output of the recovery agent — what to do after a failure."""
    failure_category: FailureCategory
    safe_to_retry: bool
    strategy: str              # human-readable strategy name
    replan_hint: str           # injected back into reasoning context
    precondition_actions: list[dict] = field(default_factory=list)  # actions to run before retry
    abort: bool = False


class RecoveryAgent:
    """
    Classifies failures and produces a RecoveryPlan.
    Does NOT execute anything — the orchestrator acts on its output.
    """

    def __init__(self, max_retries: int = 3) -> None:
        self._max_retries = max_retries

    def classify_and_plan(
        self,
        observation: ActionObservation,
        current_state: AgentState,
        page: PageState,
    ) -> RecoveryPlan:
        """
        Given a failed action observation and current agent state,
        classify the failure and produce a RecoveryPlan.
        """
        raw_category = observation.failure_category or FailureCategory.UNKNOWN.value
        category = self._classify(raw_category, observation, page)

        # Hard abort conditions
        if current_state.retry_count >= self._max_retries:
            return RecoveryPlan(
                failure_category=category,
                safe_to_retry=False,
                strategy="max_retries_exceeded",
                replan_hint="Maximum retries exceeded. Cannot recover this action.",
                abort=True,
            )

        # Detect loops — same failure category repeated
        recent_failures = current_state.failed_actions[-3:]
        recent_categories = [f.failure_category for f in recent_failures]
        if recent_categories.count(category.value) >= 3:
            return RecoveryPlan(
                failure_category=category,
                safe_to_retry=False,
                strategy="persistent_failure_loop",
                replan_hint=f"Same failure ({category.value}) occurred 3+ times. Need a fundamentally different approach.",
                abort=True,
            )

        return self._build_plan(category, observation, page)

    def _classify(
        self,
        raw: str,
        obs: ActionObservation,
        page: PageState,
    ) -> FailureCategory:
        """Refine the failure category using observation text and page context."""
        obs_text = obs.observation.lower()

        # Authentication
        if any(kw in obs_text for kw in ("login", "sign in", "authenticate", "session expired")):
            return FailureCategory.AUTHENTICATION_ERROR
        if any(kw in obs_text for kw in ("login", "sign in")) and any(
            kw in page.visible_text.lower() for kw in ("username", "password", "log in")
        ):
            return FailureCategory.AUTHENTICATION_ERROR

        # Permission
        if any(kw in obs_text for kw in ("permission", "access denied", "insufficient privilege", "403")):
            return FailureCategory.PERMISSION_ERROR

        # Validation
        if any(kw in obs_text for kw in ("validation", "required field", "invalid", "cannot be blank")):
            return FailureCategory.VALIDATION_ERROR

        # Dialog
        if page.dialogs and any(kw in obs_text for kw in ("dialog", "modal", "confirm")):
            return FailureCategory.UNEXPECTED_DIALOG

        # Timeout
        if "timeout" in obs_text or raw == FailureCategory.TIMEOUT.value:
            return FailureCategory.TIMEOUT

        # Element not found / ambiguous
        if "not found" in obs_text or "could not find" in obs_text:
            return FailureCategory.ELEMENT_NOT_FOUND
        if "multiple" in obs_text or "ambiguous" in obs_text:
            return FailureCategory.AMBIGUOUS_ELEMENT

        # Page changed unexpectedly
        if "page changed" in obs_text:
            return FailureCategory.PAGE_CHANGED

        try:
            return FailureCategory(raw)
        except ValueError:
            return FailureCategory.UNKNOWN

    def _build_plan(
        self,
        category: FailureCategory,
        obs: ActionObservation,
        page: PageState,
    ) -> RecoveryPlan:
        """
        Build a category-specific RecoveryPlan with replan hints and
        optional precondition actions.
        """
        if category == FailureCategory.AUTHENTICATION_ERROR:
            return RecoveryPlan(
                failure_category=category,
                safe_to_retry=True,
                strategy="re_authenticate",
                replan_hint=(
                    "The session has expired or the user is not logged in. "
                    "Navigate to the Salesforce login page and authenticate first, "
                    "then retry the original action."
                ),
                precondition_actions=[
                    {"action": "navigate", "target": "https://login.salesforce.com", "reason": "Re-authenticate"},
                ],
            )

        if category == FailureCategory.ELEMENT_NOT_FOUND:
            return RecoveryPlan(
                failure_category=category,
                safe_to_retry=True,
                strategy="scroll_and_retry",
                replan_hint=(
                    f"Element {obs.target!r} was not found. "
                    "Try scrolling the page to reveal it, or look for an alternative label. "
                    "The UI may use a different label than expected."
                ),
                precondition_actions=[
                    {"action": "scroll", "target": "page", "value": "down", "reason": "Reveal hidden elements"},
                    {"action": "read_page", "target": "", "reason": "Re-read page after scroll"},
                ],
            )

        if category == FailureCategory.AMBIGUOUS_ELEMENT:
            return RecoveryPlan(
                failure_category=category,
                safe_to_retry=True,
                strategy="narrow_target",
                replan_hint=(
                    f"Multiple elements matched {obs.target!r}. "
                    "Use a more specific label or add context (e.g., section name) to the target."
                ),
            )

        if category == FailureCategory.VALIDATION_ERROR:
            return RecoveryPlan(
                failure_category=category,
                safe_to_retry=True,
                strategy="fix_validation_errors",
                replan_hint=(
                    "Salesforce reported a validation error. "
                    "Read the current page to identify which field failed validation, "
                    "then correct the value before saving again."
                ),
                precondition_actions=[
                    {"action": "read_page", "target": "", "reason": "Identify validation errors"},
                ],
            )

        if category == FailureCategory.UNEXPECTED_DIALOG:
            return RecoveryPlan(
                failure_category=category,
                safe_to_retry=True,
                strategy="dismiss_dialog",
                replan_hint=(
                    "An unexpected dialog appeared. "
                    "Dismiss it by clicking Cancel or Close before retrying."
                ),
                precondition_actions=[
                    {"action": "click", "target": "Cancel", "reason": "Dismiss dialog"},
                ],
            )

        if category == FailureCategory.PERMISSION_ERROR:
            return RecoveryPlan(
                failure_category=category,
                safe_to_retry=False,
                strategy="escalate_permission",
                replan_hint=(
                    "The current user does not have permission to perform this action. "
                    "This task cannot be completed with the current Salesforce profile/role. "
                    "Human intervention required."
                ),
                abort=True,
            )

        if category == FailureCategory.TIMEOUT:
            return RecoveryPlan(
                failure_category=category,
                safe_to_retry=True,
                strategy="wait_and_retry",
                replan_hint=(
                    "The page timed out. Wait for the page to load, then retry. "
                    "Use a 'wait' action for a loading indicator before proceeding."
                ),
                precondition_actions=[
                    {"action": "wait", "target": "Loading", "reason": "Wait for page to finish loading"},
                    {"action": "read_page", "target": "", "reason": "Re-read page after wait"},
                ],
            )

        if category == FailureCategory.PAGE_CHANGED:
            return RecoveryPlan(
                failure_category=category,
                safe_to_retry=True,
                strategy="re_read_and_replan",
                replan_hint=(
                    "The page changed unexpectedly. "
                    "Re-read the current page to understand the new context before re-planning."
                ),
                precondition_actions=[
                    {"action": "read_page", "target": "", "reason": "Re-read after unexpected page change"},
                ],
            )

        # Default
        return RecoveryPlan(
            failure_category=category,
            safe_to_retry=True,
            strategy="generic_retry",
            replan_hint=(
                f"An unknown error occurred: {obs.observation[:200]}. "
                "Re-read the page and try a different approach."
            ),
            precondition_actions=[
                {"action": "read_page", "target": "", "reason": "Re-read page to understand current state"},
            ],
        )
