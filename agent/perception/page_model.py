"""
agent/perception/page_model.py

Pydantic dataclasses that describe a complete semantic snapshot of a browser page.
No coordinates — only semantic labels, roles, and text.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Sub-models
# ─────────────────────────────────────────────────────────────────────────────

class InputState(BaseModel):
    label: str | None = None          # visible label text
    placeholder: str | None = None
    input_type: str = "text"          # text | password | checkbox | radio | select | textarea
    name: str | None = None
    value: str | None = None
    is_required: bool = False
    is_disabled: bool = False
    is_readonly: bool = False
    aria_label: str | None = None


class ButtonState(BaseModel):
    label: str                         # The text / aria-label of the button
    is_disabled: bool = False
    button_type: str = "button"        # button | submit | reset
    aria_label: str | None = None


class LinkState(BaseModel):
    text: str
    href: str | None = None
    aria_label: str | None = None


class FormState(BaseModel):
    form_id: str | None = None
    action: str | None = None
    inputs: list[InputState] = Field(default_factory=list)
    submit_button: ButtonState | None = None


class TableState(BaseModel):
    caption: str | None = None
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class AlertState(BaseModel):
    level: str        # success | error | warning | info
    message: str


class DialogState(BaseModel):
    title: str | None = None
    body: str | None = None
    buttons: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Salesforce-specific page type detection
# ─────────────────────────────────────────────────────────────────────────────

class SalesforceContext(BaseModel):
    """Detected Salesforce environment and current object context."""
    environment: str = "unknown"       # trailhead | lightning | classic | setup | unknown
    app_name: str | None = None
    current_object: str | None = None  # e.g. "Account", "Lead", "Opportunity"
    page_type: str | None = None       # list | record | new | edit | setup | report | dashboard
    module_name: str | None = None     # Trailhead module
    unit_name: str | None = None       # Trailhead unit
    task_description: str | None = None
    progress_pct: int | None = None    # 0-100


# ─────────────────────────────────────────────────────────────────────────────
# Master page snapshot
# ─────────────────────────────────────────────────────────────────────────────

class PageState(BaseModel):
    """Complete semantic snapshot of the current browser page."""

    # Core identifiers
    url: str
    title: str
    snapshot_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Visible structure
    headings: list[str] = Field(default_factory=list)
    visible_text: str = ""            # Full visible text (truncated to ~4000 chars)
    paragraphs: list[str] = Field(default_factory=list)

    # Interactive elements
    forms: list[FormState] = Field(default_factory=list)
    inputs: list[InputState] = Field(default_factory=list)   # standalone (not in a form)
    buttons: list[ButtonState] = Field(default_factory=list)
    links: list[LinkState] = Field(default_factory=list)
    tables: list[TableState] = Field(default_factory=list)

    # Feedback elements
    dialogs: list[DialogState] = Field(default_factory=list)
    alerts: list[AlertState] = Field(default_factory=list)
    toasts: list[AlertState] = Field(default_factory=list)   # Salesforce Lightning toasts

    # Selected/current values
    selected_values: dict[str, str] = Field(default_factory=dict)

    # Salesforce-specific context
    salesforce: SalesforceContext = Field(default_factory=SalesforceContext)

    # Raw extras (for edge cases)
    extra: dict[str, Any] = Field(default_factory=dict)

    def summary(self) -> str:
        """Human-readable one-paragraph summary of this page state."""
        lines = [
            f"URL: {self.url}",
            f"Title: {self.title}",
            f"Environment: {self.salesforce.environment}",
        ]
        if self.headings:
            lines.append(f"Headings: {', '.join(self.headings[:5])}")
        if self.alerts:
            for a in self.alerts:
                lines.append(f"[{a.level.upper()}] {a.message}")
        if self.toasts:
            for t in self.toasts:
                lines.append(f"[TOAST/{t.level.upper()}] {t.message}")
        if self.dialogs:
            for d in self.dialogs:
                lines.append(f"[DIALOG] {d.title}: {d.body}")
        btn_labels = [b.label for b in self.buttons[:10]]
        if btn_labels:
            lines.append(f"Buttons: {', '.join(btn_labels)}")
        return "\n".join(lines)
