"""
agent/perception/browser_agent.py

Playwright-based Browser Perception Agent.
Produces a fully semantic PageState snapshot from the current browser page.
No hard-coded coordinates — uses roles, labels, and text.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

from config import cfg
from agent.perception.page_model import (
    AlertState,
    ButtonState,
    DialogState,
    FormState,
    InputState,
    LinkState,
    PageState,
    SalesforceContext,
    TableState,
)

from agent.perception.hud import HUDOverlay

_VISIBLE_TEXT_MAX = 5000


class BrowserAgent:
    """
    Manages a Playwright browser session and produces PageState snapshots.

    Usage (async):
        async with BrowserAgent() as agent:
            await agent.navigate("https://trailhead.salesforce.com")
            state = await agent.snapshot()
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._last_hud: dict[str, str] | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def launch(self) -> None:
        """Start Playwright and open a new browser window."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=cfg.HEADLESS,
            channel="msedge",
            args=["--start-maximized"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            no_viewport=False,
        )
        self._page = await self._context.new_page()

    async def close(self) -> None:
        """Cleanly shut down the browser."""
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def __aenter__(self) -> "BrowserAgent":
        await self.launch()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ── Navigation ────────────────────────────────────────────────────────────

    @property
    def page(self) -> Page:
        assert self._page is not None, "BrowserAgent not launched."
        return self._page

    async def navigate(self, url: str) -> None:
        await self.page.goto(url, timeout=cfg.NAVIGATION_TIMEOUT_MS, wait_until="domcontentloaded")

    async def go_back(self) -> None:
        await self.page.go_back(timeout=cfg.NAVIGATION_TIMEOUT_MS)

    # ── HUD & Overlay ─────────────────────────────────────────────────────────

    async def update_hud(
        self,
        status: str,
        phase: str = "RUNNING",
        detail: str = "",
        style_type: str = "active",
    ) -> None:
        """Update the persistent on-screen HUD text box."""
        self._last_hud = {
            "status": status,
            "phase": phase,
            "detail": detail,
            "style_type": style_type,
        }
        if self._page and not self._page.is_closed():
            await HUDOverlay.update(
                self.page,
                status=status,
                phase=phase,
                detail=detail,
                style_type=style_type,
            )

    async def show_completion_modal(
        self,
        title: str,
        status: str,
        message: str,
        details: list[str] | None = None,
    ) -> None:
        """Show the final completion dialog box on screen."""
        if self._page and not self._page.is_closed():
            await HUDOverlay.show_completion_modal(
                self.page,
                title=title,
                status=status,
                message=message,
                details=details,
            )

    # ── Snapshot ──────────────────────────────────────────────────────────────

    async def snapshot(self) -> PageState:
        """Return a complete semantic PageState for the current page."""
        page = self.page
        await self._wait_for_stable(page)

        # Re-inject HUD text box if previously rendered so it persists constantly
        if self._last_hud and not page.is_closed():
            await HUDOverlay.update(
                page,
                status=self._last_hud["status"],
                phase=self._last_hud["phase"],
                detail=self._last_hud["detail"],
                style_type=self._last_hud["style_type"],
            )

        url = page.url
        title = await page.title()

        headings, paragraphs, visible_text = await self._extract_text(page)
        inputs, forms = await self._extract_forms_and_inputs(page)
        buttons = await self._extract_buttons(page)
        links = await self._extract_links(page)
        tables = await self._extract_tables(page)
        dialogs = await self._extract_dialogs(page)
        alerts, toasts = await self._extract_alerts_and_toasts(page)
        selected_values = await self._extract_selected_values(page)
        sf_context = await self._detect_salesforce_context(page, url, title, visible_text)

        return PageState(
            url=url,
            title=title,
            headings=headings,
            visible_text=visible_text[:_VISIBLE_TEXT_MAX],
            paragraphs=paragraphs[:20],
            forms=forms,
            inputs=inputs,
            buttons=buttons,
            links=links[:40],
            tables=tables,
            dialogs=dialogs,
            alerts=alerts,
            toasts=toasts,
            selected_values=selected_values,
            salesforce=sf_context,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _wait_for_stable(self, page: Page) -> None:
        """Wait until the page is not loading."""
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass  # timeout — proceed anyway

    async def _extract_text(self, page: Page) -> tuple[list[str], list[str], str]:
        result: dict = await page.evaluate("""() => {
            const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]
                .map(h => h.innerText.trim()).filter(t => t);
            const paragraphs = [...document.querySelectorAll('p,li')]
                .map(p => p.innerText.trim()).filter(t => t && t.length > 10);
            const body = document.body ? document.body.innerText.trim() : '';
            return {headings, paragraphs, body};
        }""")
        return result["headings"], result["paragraphs"], result["body"]

    async def _extract_forms_and_inputs(
        self, page: Page
    ) -> tuple[list[InputState], list[FormState]]:
        raw: list[dict] = await page.evaluate("""() => {
            function getLabel(el) {
                if (el.id) {
                    const lbl = document.querySelector(`label[for="${el.id}"]`);
                    if (lbl) return lbl.innerText.trim();
                }
                const parent = el.closest('label,div[class*="form"],lightning-input');
                if (parent) {
                    const lbl = parent.querySelector('label,span[class*="label"]');
                    if (lbl) return lbl.innerText.trim();
                }
                return el.getAttribute('aria-label') || el.placeholder || null;
            }
            const inputs = [...document.querySelectorAll(
                'input:not([type=hidden]),textarea,select'
            )].map(el => ({
                label: getLabel(el),
                placeholder: el.placeholder || null,
                input_type: el.type || el.tagName.toLowerCase(),
                name: el.name || null,
                value: el.type === 'checkbox' ? String(el.checked) : (el.value || null),
                is_required: el.required,
                is_disabled: el.disabled,
                is_readonly: el.readOnly || false,
                aria_label: el.getAttribute('aria-label') || null,
            }));
            const forms = [...document.querySelectorAll('form')].map(f => ({
                form_id: f.id || null,
                action: f.action || null,
                inputs: [...f.querySelectorAll(
                    'input:not([type=hidden]),textarea,select'
                )].map(el => ({
                    label: getLabel(el),
                    placeholder: el.placeholder || null,
                    input_type: el.type || el.tagName.toLowerCase(),
                    name: el.name || null,
                    value: el.type === 'checkbox' ? String(el.checked) : (el.value || null),
                    is_required: el.required,
                    is_disabled: el.disabled,
                    is_readonly: el.readOnly || false,
                    aria_label: el.getAttribute('aria-label') || null,
                })),
            }));
            return {inputs, forms};
        }""")
        inputs = [InputState(**i) for i in raw["inputs"]]
        forms = [FormState(**f) for f in raw["forms"]]
        return inputs, forms

    async def _extract_buttons(self, page: Page) -> list[ButtonState]:
        raw: list[dict] = await page.evaluate("""() => {
            return [...document.querySelectorAll(
                'button,input[type=button],input[type=submit],[role=button],a.btn,a[class*="button"]'
            )].map(el => ({
                label: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim(),
                is_disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
                button_type: el.type || 'button',
                aria_label: el.getAttribute('aria-label') || null,
            })).filter(b => b.label);
        }""")
        seen: set[str] = set()
        buttons: list[ButtonState] = []
        for b in raw:
            key = b["label"].lower()
            if key not in seen:
                seen.add(key)
                buttons.append(ButtonState(**b))
        return buttons

    async def _extract_links(self, page: Page) -> list[LinkState]:
        raw: list[dict] = await page.evaluate("""() => {
            return [...document.querySelectorAll('a[href]')].map(a => ({
                text: (a.innerText || a.getAttribute('aria-label') || '').trim(),
                href: a.href,
                aria_label: a.getAttribute('aria-label') || null,
            })).filter(l => l.text);
        }""")
        return [LinkState(**l) for l in raw]

    async def _extract_tables(self, page: Page) -> list[TableState]:
        raw: list[dict] = await page.evaluate("""() => {
            return [...document.querySelectorAll('table')].map(t => {
                const caption = t.caption ? t.caption.innerText.trim() : null;
                const headers = [...t.querySelectorAll('th')].map(th => th.innerText.trim());
                const rows = [...t.querySelectorAll('tbody tr')].map(tr =>
                    [...tr.querySelectorAll('td')].map(td => td.innerText.trim())
                );
                return {caption, headers, rows};
            });
        }""")
        return [TableState(**t) for t in raw]

    async def _extract_dialogs(self, page: Page) -> list[DialogState]:
        raw: list[dict] = await page.evaluate("""() => {
            return [...document.querySelectorAll(
                '[role=dialog],[role=alertdialog],.modal,.slds-modal'
            )].map(d => ({
                title: (d.querySelector('h1,h2,[class*="title"]')?.innerText || '').trim() || null,
                body: (d.querySelector('[class*="body"],[class*="content"]')?.innerText || '').trim() || null,
                buttons: [...d.querySelectorAll('button')].map(b => b.innerText.trim()).filter(t => t),
            }));
        }""")
        return [DialogState(**d) for d in raw]

    async def _extract_alerts_and_toasts(
        self, page: Page
    ) -> tuple[list[AlertState], list[AlertState]]:
        raw: dict = await page.evaluate("""() => {
            function classify(el) {
                const cls = el.className || '';
                const role = el.getAttribute('role') || '';
                if (cls.includes('error') || role === 'alert' && cls.includes('error')) return 'error';
                if (cls.includes('success')) return 'success';
                if (cls.includes('warning') || cls.includes('warn')) return 'warning';
                return 'info';
            }
            const alerts = [...document.querySelectorAll(
                '[role=alert],[role=status],[class*="alert"],[class*="message--error"],[class*="notistack"]'
            )].map(el => ({level: classify(el), message: el.innerText.trim()}))
              .filter(a => a.message);
            const toasts = [...document.querySelectorAll(
                '.toastContainer [class*="toast"],[class*="slds-notify--toast"],[class*="slds-toast"]'
            )].map(el => ({level: classify(el), message: el.innerText.trim()}))
              .filter(a => a.message);
            return {alerts, toasts};
        }""")
        alerts = [AlertState(**a) for a in raw.get("alerts", [])]
        toasts = [AlertState(**a) for a in raw.get("toasts", [])]
        return alerts, toasts

    async def _extract_selected_values(self, page: Page) -> dict[str, str]:
        raw: list[dict] = await page.evaluate("""() => {
            return [...document.querySelectorAll('select')].map(sel => ({
                name: sel.name || sel.id || sel.getAttribute('aria-label') || 'unknown',
                value: sel.options[sel.selectedIndex]?.text || sel.value || '',
            }));
        }""")
        return {item["name"]: item["value"] for item in raw if item.get("name")}

    async def _detect_salesforce_context(
        self, page: Page, url: str, title: str, text: str
    ) -> SalesforceContext:
        env = "unknown"
        if "trailhead" in url:
            env = "trailhead"
        elif "lightning.force.com" in url or "lightning/n/" in url or "lightning/o/" in url:
            env = "lightning"
        elif "salesforce.com/setup" in url or "/lightning/setup/" in url:
            env = "setup"
        elif "salesforce.com" in url:
            env = "classic"

        # Trailhead: extract module/unit/task
        module_name: str | None = None
        unit_name: str | None = None
        task_description: str | None = None
        progress_pct: int | None = None
        current_object: str | None = None
        page_type: str | None = None

        if env == "trailhead":
            # Module name typically in h1 or the breadcrumb
            raw: dict = await page.evaluate("""() => {
                const h1 = document.querySelector('h1')?.innerText?.trim() || null;
                const breadcrumbs = [...document.querySelectorAll(
                    'nav[aria-label*="breadcrumb"] a,ol.breadcrumbs li'
                )].map(b => b.innerText.trim());
                const progressBar = document.querySelector('[aria-valuenow]');
                const progress = progressBar ? parseInt(progressBar.getAttribute('aria-valuenow')) : null;
                const taskEl = document.querySelector('.challenge-content,.task-content,[class*="challenge"]');
                const task = taskEl ? taskEl.innerText.trim().slice(0, 500) : null;
                return {h1, breadcrumbs, progress, task};
            }""")
            if raw.get("breadcrumbs"):
                crumbs = raw["breadcrumbs"]
                module_name = crumbs[0] if len(crumbs) > 0 else None
                unit_name = crumbs[1] if len(crumbs) > 1 else raw.get("h1")
            else:
                unit_name = raw.get("h1")
            task_description = raw.get("task")
            progress_pct = raw.get("progress")

        elif env in ("lightning", "setup", "classic"):
            # Try to infer the current Salesforce object from the URL
            obj_match = re.search(r"/lightning/o/(\w+)/", url) or re.search(r"/(\w+)/home", url)
            if obj_match:
                current_object = obj_match.group(1)
            # Page type
            if "/new" in url:
                page_type = "new"
            elif "/edit" in url:
                page_type = "edit"
            elif "/view" in url or re.search(r"/\w{18}/view", url):
                page_type = "record"
            elif "/list" in url:
                page_type = "list"
            elif "/setup/" in url:
                page_type = "setup"

        # App name from Lightning header
        app_name: str | None = None
        if env in ("lightning", "setup"):
            try:
                app_name = await page.locator(".appName,.slds-context-bar__app-name").inner_text(timeout=2000)
                app_name = app_name.strip() or None
            except Exception:
                pass

        return SalesforceContext(
            environment=env,
            app_name=app_name,
            current_object=current_object,
            page_type=page_type,
            module_name=module_name,
            unit_name=unit_name,
            task_description=task_description,
            progress_pct=progress_pct,
        )
