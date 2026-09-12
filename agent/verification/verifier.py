"""
agent/verification/verifier.py

Verification Agent — independently checks whether a browser action
actually succeeded by comparing pre/post PageState snapshots.

Principle: "click succeeded" ≠ "task succeeded".
The success criterion is the resulting application state.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent.actions.action_agent import ActionObservation
from agent.perception.browser_agent import BrowserAgent
from agent.perception.page_model import PageState
from agent.state import VerificationRecord


@dataclass
class VerificationResult:
    success: bool
    evidence: list[str] = field(default_factory=list)
    discrepancies: list[str] = field(default_factory=list)
    post_state: PageState | None = None


class Verifier:
    """
    Performs post-action state verification.
    Called after each action (or after a group of related actions).
    """

    def __init__(self, browser_agent: BrowserAgent) -> None:
        self._browser = browser_agent

    async def verify(
        self,
        action_obs: ActionObservation,
        expected: list[str],
        pre_state: PageState | None = None,
    ) -> VerificationResult:
        """
        Verify whether `action_obs` achieved its expected outcome.

        Parameters
        ----------
        action_obs  The observation from the action agent.
        expected    List of free-text expectations (from ActionPlan.verification).
        pre_state   PageState BEFORE the action (for diff-based checks).
        """
        # Always take a fresh snapshot AFTER the action
        post_state = action_obs.page_state or await self._browser.snapshot()

        evidence: list[str] = []
        discrepancies: list[str] = []

        # ── 1. Basic action result ────────────────────────────────────────────
        if action_obs.result == "failure":
            discrepancies.append(
                f"Action {action_obs.action!r} reported failure: {action_obs.observation}"
            )
            return VerificationResult(
                success=False,
                evidence=evidence,
                discrepancies=discrepancies,
                post_state=post_state,
            )

        evidence.append(f"Action {action_obs.action!r} completed: {action_obs.observation[:200]}")

        # ── 2. Check for Salesforce error toasts / alerts ─────────────────────
        for toast in post_state.toasts:
            if toast.level == "error":
                discrepancies.append(f"Salesforce error toast: {toast.message}")
            elif toast.level == "success":
                evidence.append(f"Salesforce success toast: {toast.message}")

        for alert in post_state.alerts:
            if alert.level == "error":
                discrepancies.append(f"Page error alert: {alert.message}")
            elif alert.level == "success":
                evidence.append(f"Page success alert: {alert.message}")

        # ── 3. Check for validation errors (form) ────────────────────────────
        validation_errors = await self._check_validation_errors()
        if validation_errors:
            for err in validation_errors:
                discrepancies.append(f"Validation error: {err}")

        # ── 4. Navigation verification ────────────────────────────────────────
        if action_obs.action == "navigate":
            if action_obs.new_url and action_obs.new_url != post_state.url:
                discrepancies.append(
                    f"URL mismatch after navigate: expected {action_obs.new_url!r}, got {post_state.url!r}"
                )
            else:
                evidence.append(f"Navigation confirmed. URL: {post_state.url}")

        # ── 5. Free-text expectation matching ─────────────────────────────────
        for expectation in expected:
            matched = self._check_expectation(expectation, post_state)
            if matched:
                evidence.append(f"✓ Expected condition met: {expectation}")
            else:
                # Soft check — not a hard failure unless it's the only criterion
                discrepancies.append(f"Unconfirmed expectation: {expectation}")

        # ── 6. Pre/post diff ──────────────────────────────────────────────────
        if pre_state:
            diff_notes = self._diff_states(pre_state, post_state)
            evidence.extend(diff_notes)

        # ── Verdict ───────────────────────────────────────────────────────────
        # Succeed if: no hard errors AND the action itself succeeded
        hard_errors = [d for d in discrepancies if "error" in d.lower() or "mismatch" in d.lower()]
        success = len(hard_errors) == 0

        return VerificationResult(
            success=success,
            evidence=evidence,
            discrepancies=discrepancies,
            post_state=post_state,
        )

    async def verify_task_complete(
        self, success_criteria: list[str]
    ) -> VerificationResult:
        """
        Independent task-level verification — check whether the overall
        task has been completed by examining the current page state.
        """
        post_state = await self._browser.snapshot()
        evidence: list[str] = []
        discrepancies: list[str] = []

        for criterion in success_criteria:
            matched = self._check_expectation(criterion, post_state)
            if matched:
                evidence.append(f"✓ Task success criterion met: {criterion}")
            else:
                discrepancies.append(f"✗ Task success criterion NOT met: {criterion}")

        # Also check for any outstanding error toasts
        for toast in post_state.toasts:
            if toast.level == "error":
                discrepancies.append(f"Outstanding error toast: {toast.message}")

        success = len(discrepancies) == 0
        return VerificationResult(
            success=success,
            evidence=evidence,
            discrepancies=discrepancies,
            post_state=post_state,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _check_validation_errors(self) -> list[str]:
        """Look for Salesforce Lightning / Classic validation error messages."""
        try:
            errors: list[str] = await self._browser.page.evaluate("""() => {
                const selectors = [
                    '.errorMsg', '.slds-has-error .slds-form-error',
                    '[class*="error"][class*="message"]',
                    '.forceFormError', 'p.error',
                ];
                const msgs = [];
                selectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => {
                        const t = el.innerText.trim();
                        if (t) msgs.push(t);
                    });
                });
                return [...new Set(msgs)];
            }""")
            return errors
        except Exception:
            return []

    def _check_expectation(self, expectation: str, state: PageState) -> bool:
        """
        Check whether a free-text expectation string is satisfied by
        the current PageState. Uses simple keyword matching.
        """
        exp_lower = expectation.lower()
        searchable = (
            state.visible_text + " " +
            " ".join(state.headings) + " " +
            " ".join(t.message for t in state.toasts) + " " +
            " ".join(a.message for a in state.alerts)
        ).lower()

        # Direct text presence
        if exp_lower in searchable:
            return True

        # URL-based check
        if "url" in exp_lower and state.url:
            url_fragment = expectation.split("url")[-1].strip().strip("':\"").lower()
            if url_fragment and url_fragment in state.url.lower():
                return True

        # Success toast present
        if "success" in exp_lower and any(t.level == "success" for t in state.toasts):
            return True

        # Saved / created
        if any(kw in exp_lower for kw in ("saved", "created", "updated", "deleted")):
            if any(
                kw in searchable
                for kw in ("was saved", "was created", "saved", "created", "updated", "successfully")
            ):
                return True

        return False

    def _diff_states(self, pre: PageState, post: PageState) -> list[str]:
        """Return notes about meaningful changes between pre and post states."""
        notes: list[str] = []
        if pre.url != post.url:
            notes.append(f"URL changed: {pre.url!r} → {post.url!r}")
        if pre.title != post.title:
            notes.append(f"Page title changed: {pre.title!r} → {post.title!r}")
        pre_headings = set(pre.headings)
        post_headings = set(post.headings)
        new_headings = post_headings - pre_headings
        if new_headings:
            notes.append(f"New headings appeared: {', '.join(new_headings)}")
        return notes

    def to_state_record(self, result: "VerificationResult") -> VerificationRecord:
        return VerificationRecord(
            success=result.success,
            evidence=result.evidence,
            discrepancies=result.discrepancies,
        )
