"""
agent/actions/action_agent.py

Action Agent — translates PlannedActions from the ActionPlan into Playwright
browser operations. Each action returns an ActionObservation.

Design principles:
  • Semantic targeting only — uses role/label/text, never pixel coords.
  • Every action observes its result before returning.
  • Never executes the entire plan blindly; caller must ACT-OBSERVE-VERIFY per step.
  • Destructive actions require explicit external confirmation before running.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from config import cfg
from agent.perception.browser_agent import BrowserAgent
from agent.perception.page_model import PageState
from agent.reasoning.reasoning_agent import PlannedAction
from agent.state import FailureCategory


# ─────────────────────────────────────────────────────────────────────────────
# Output model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ActionObservation:
    action: str
    target: str
    value: str | None
    result: str              # "success" | "failure" | "skipped"
    observation: str         # human-readable description of what happened
    failure_category: str | None = None
    new_url: str | None = None
    page_state: PageState | None = None   # snapshot taken after action


# ─────────────────────────────────────────────────────────────────────────────
# Action agent
# ─────────────────────────────────────────────────────────────────────────────

class ActionAgent:
    """
    Executes one PlannedAction at a time against a live Playwright page.
    Returns an ActionObservation after every action.
    """

    def __init__(self, browser_agent: BrowserAgent) -> None:
        self._browser = browser_agent

    async def execute(self, action: PlannedAction) -> ActionObservation:
        """
        Dispatch a single planned action and return its observation.
        The caller decides whether to proceed to the next action.
        """
        handler = {
            "navigate":     self._navigate,
            "click":        self._click,
            "type":         self._type,
            "select":       self._select,
            "check":        self._check,
            "uncheck":      self._uncheck,
            "scroll":       self._scroll,
            "wait":         self._wait,
            "go_back":      self._go_back,
            "read_page":    self._read_page,
            "find_element": self._find_element,
            "switch_tab":   self._switch_tab,
        }.get(action.action)

        if handler is None:
            return ActionObservation(
                action=action.action,
                target=action.target,
                value=action.value,
                result="failure",
                observation=f"Unknown action type: {action.action!r}",
                failure_category=FailureCategory.UNKNOWN.value,
            )

        try:
            return await handler(action)
        except PlaywrightTimeout as e:
            return ActionObservation(
                action=action.action,
                target=action.target,
                value=action.value,
                result="failure",
                observation=f"Timeout: {e}",
                failure_category=FailureCategory.TIMEOUT.value,
            )
        except Exception as e:
            return ActionObservation(
                action=action.action,
                target=action.target,
                value=action.value,
                result="failure",
                observation=f"Unexpected error: {type(e).__name__}: {e}",
                failure_category=FailureCategory.UNKNOWN.value,
            )

    # ── Primitive handlers ────────────────────────────────────────────────────

    async def _navigate(self, action: PlannedAction) -> ActionObservation:
        target = action.target
        if not target.startswith("http"):
            target = "https://" + target
        await self._browser.navigate(target)
        await asyncio.sleep(0.5)
        page_state = await self._browser.snapshot()
        return ActionObservation(
            action="navigate",
            target=action.target,
            value=None,
            result="success",
            observation=f"Navigated to {target}. Page title: {page_state.title}",
            new_url=page_state.url,
            page_state=page_state,
        )

    async def _click(self, action: PlannedAction) -> ActionObservation:
        page: Page = self._browser.page
        target = action.target

        # Try semantic locators in priority order
        locator = None
        strategies = [
            lambda: page.get_by_role("button", name=target),
            lambda: page.get_by_role("link", name=target),
            lambda: page.get_by_label(target),
            lambda: page.get_by_text(target, exact=False),
            lambda: page.locator(f"[aria-label='{target}']"),
            lambda: page.locator(f"[title='{target}']"),
        ]

        last_error: Exception | None = None
        for strategy in strategies:
            try:
                loc = strategy()
                await loc.first.click(timeout=cfg.ACTION_TIMEOUT_MS)
                locator = loc
                break
            except Exception as e:
                last_error = e
                continue

        if locator is None:
            return ActionObservation(
                action="click",
                target=target,
                value=None,
                result="failure",
                observation=f"Could not find clickable element: {target!r}. Last error: {last_error}",
                failure_category=FailureCategory.ELEMENT_NOT_FOUND.value,
            )

        await asyncio.sleep(0.5)
        page_state = await self._browser.snapshot()
        return ActionObservation(
            action="click",
            target=target,
            value=None,
            result="success",
            observation=f"Clicked {target!r}. New page: {page_state.title}",
            new_url=page_state.url,
            page_state=page_state,
        )

    async def _type(self, action: PlannedAction) -> ActionObservation:
        page: Page = self._browser.page
        target = action.target
        value = action.value or ""

        # Try label-based locators
        strategies = [
            lambda: page.get_by_label(target),
            lambda: page.get_by_placeholder(target),
            lambda: page.locator(f"input[name='{target}']"),
            lambda: page.locator(f"textarea[name='{target}']"),
            lambda: page.locator(f"[aria-label='{target}']"),
        ]

        last_error: Exception | None = None
        for strategy in strategies:
            try:
                loc = strategy()
                await loc.first.fill(value, timeout=cfg.ACTION_TIMEOUT_MS)
                return ActionObservation(
                    action="type",
                    target=target,
                    value=value,
                    result="success",
                    observation=f"Filled field {target!r} with {value!r}",
                )
            except Exception as e:
                last_error = e

        return ActionObservation(
            action="type",
            target=target,
            value=value,
            result="failure",
            observation=f"Could not find input field: {target!r}. Error: {last_error}",
            failure_category=FailureCategory.ELEMENT_NOT_FOUND.value,
        )

    async def _select(self, action: PlannedAction) -> ActionObservation:
        page: Page = self._browser.page
        target = action.target
        value = action.value or ""

        try:
            loc = page.get_by_label(target)
            await loc.first.select_option(label=value, timeout=cfg.ACTION_TIMEOUT_MS)
            return ActionObservation(
                action="select",
                target=target,
                value=value,
                result="success",
                observation=f"Selected {value!r} in {target!r}",
            )
        except Exception:
            pass

        try:
            loc = page.locator(f"select[name='{target}'],select[aria-label='{target}']")
            await loc.first.select_option(label=value, timeout=cfg.ACTION_TIMEOUT_MS)
            return ActionObservation(
                action="select",
                target=target,
                value=value,
                result="success",
                observation=f"Selected {value!r} in {target!r} (by name/aria)",
            )
        except Exception as e:
            return ActionObservation(
                action="select",
                target=target,
                value=value,
                result="failure",
                observation=f"Could not select {value!r} in {target!r}: {e}",
                failure_category=FailureCategory.ELEMENT_NOT_FOUND.value,
            )

    async def _check(self, action: PlannedAction) -> ActionObservation:
        page: Page = self._browser.page
        try:
            loc = page.get_by_label(action.target)
            await loc.first.check(timeout=cfg.ACTION_TIMEOUT_MS)
            return ActionObservation(
                action="check",
                target=action.target,
                value=None,
                result="success",
                observation=f"Checked checkbox: {action.target!r}",
            )
        except Exception as e:
            return ActionObservation(
                action="check",
                target=action.target,
                value=None,
                result="failure",
                observation=f"Could not check {action.target!r}: {e}",
                failure_category=FailureCategory.ELEMENT_NOT_FOUND.value,
            )

    async def _uncheck(self, action: PlannedAction) -> ActionObservation:
        page: Page = self._browser.page
        try:
            loc = page.get_by_label(action.target)
            await loc.first.uncheck(timeout=cfg.ACTION_TIMEOUT_MS)
            return ActionObservation(
                action="uncheck",
                target=action.target,
                value=None,
                result="success",
                observation=f"Unchecked checkbox: {action.target!r}",
            )
        except Exception as e:
            return ActionObservation(
                action="uncheck",
                target=action.target,
                value=None,
                result="failure",
                observation=f"Could not uncheck {action.target!r}: {e}",
                failure_category=FailureCategory.ELEMENT_NOT_FOUND.value,
            )

    async def _scroll(self, action: PlannedAction) -> ActionObservation:
        page: Page = self._browser.page
        direction = (action.value or "down").lower()
        delta = 500 if direction == "down" else -500
        await page.evaluate(f"window.scrollBy(0, {delta})")
        return ActionObservation(
            action="scroll",
            target=action.target,
            value=direction,
            result="success",
            observation=f"Scrolled {direction}",
        )

    async def _wait(self, action: PlannedAction) -> ActionObservation:
        page: Page = self._browser.page
        target = action.target
        try:
            await page.wait_for_selector(
                f"text={target}",
                timeout=cfg.ACTION_TIMEOUT_MS,
                state="visible",
            )
            return ActionObservation(
                action="wait",
                target=target,
                value=None,
                result="success",
                observation=f"Element/text appeared: {target!r}",
            )
        except PlaywrightTimeout:
            return ActionObservation(
                action="wait",
                target=target,
                value=None,
                result="failure",
                observation=f"Timed out waiting for: {target!r}",
                failure_category=FailureCategory.TIMEOUT.value,
            )

    async def _go_back(self, action: PlannedAction) -> ActionObservation:
        await self._browser.go_back()
        await asyncio.sleep(0.5)
        page_state = await self._browser.snapshot()
        return ActionObservation(
            action="go_back",
            target="",
            value=None,
            result="success",
            observation=f"Navigated back. Now at: {page_state.title}",
            new_url=page_state.url,
            page_state=page_state,
        )

    async def _read_page(self, action: PlannedAction) -> ActionObservation:
        page_state = await self._browser.snapshot()
        return ActionObservation(
            action="read_page",
            target="",
            value=None,
            result="success",
            observation=f"Page snapshot taken. Title: {page_state.title}",
            new_url=page_state.url,
            page_state=page_state,
        )

    async def _find_element(self, action: PlannedAction) -> ActionObservation:
        page: Page = self._browser.page
        target = action.target
        strategies = [
            lambda: page.get_by_text(target, exact=False),
            lambda: page.get_by_label(target),
            lambda: page.get_by_role("heading", name=target),
        ]
        for strategy in strategies:
            try:
                loc = strategy()
                count = await loc.count()
                if count > 0:
                    text = await loc.first.inner_text()
                    return ActionObservation(
                        action="find_element",
                        target=target,
                        value=None,
                        result="success",
                        observation=f"Found {count} element(s) matching {target!r}. First: {text[:100]!r}",
                    )
            except Exception:
                continue

        return ActionObservation(
            action="find_element",
            target=target,
            value=None,
            result="failure",
            observation=f"Element not found: {target!r}",
            failure_category=FailureCategory.ELEMENT_NOT_FOUND.value,
        )

    async def _switch_tab(self, action: PlannedAction) -> ActionObservation:
        try:
            idx = int(action.value or "0")
            ctx = self._browser._context
            assert ctx is not None
            pages = ctx.pages
            if idx >= len(pages):
                return ActionObservation(
                    action="switch_tab",
                    target=action.target,
                    value=str(idx),
                    result="failure",
                    observation=f"Tab index {idx} out of range (have {len(pages)} tabs)",
                    failure_category=FailureCategory.ELEMENT_NOT_FOUND.value,
                )
            self._browser._page = pages[idx]
            await pages[idx].bring_to_front()
            ps = await self._browser.snapshot()
            return ActionObservation(
                action="switch_tab",
                target=action.target,
                value=str(idx),
                result="success",
                observation=f"Switched to tab {idx}: {ps.title}",
                page_state=ps,
            )
        except Exception as e:
            return ActionObservation(
                action="switch_tab",
                target=action.target,
                value=action.value,
                result="failure",
                observation=str(e),
                failure_category=FailureCategory.UNKNOWN.value,
            )
