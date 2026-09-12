"""
observability/tracer.py

Human-readable live trace output using Rich.
Emits [OBSERVE], [UNDERSTAND], [RESEARCH], [REASON],
[ACTION], [OBSERVE], [VERIFY], [STATE], [NEXT] sections
to the console in real time.
"""
from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text

from config import cfg

_console = Console(safe_box=True)

# Tag → (color, emoji)
_TAGS: dict[str, tuple[str, str]] = {
    "OBSERVE":     ("cyan",          "👁 "),
    "UNDERSTAND":  ("blue",          "🧠 "),
    "RESEARCH":    ("magenta",       "🔍 "),
    "REASON":      ("yellow",        "⚙ "),
    "ACTION":      ("green",         "▶ "),
    "VERIFY":      ("bright_green",  "✅ "),
    "VERIFY_FAIL": ("bright_red",    "❌ "),
    "STATE":       ("white",         "📋 "),
    "NEXT":        ("bright_cyan",   "➡ "),
    "RECOVER":     ("orange3",       "🔄 "),
    "ERROR":       ("red",           "💥 "),
    "WARN":        ("yellow",        "⚠ "),
    "COMPLETE":    ("bright_green",  "🎉 "),
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def trace(tag: str, message: str, detail: str | None = None) -> None:
    """Emit a single trace line to the console."""
    if not cfg.TRACE_TO_CONSOLE:
        return

    color, emoji = _TAGS.get(tag, ("white", "•"))
    header = Text(f"[{_ts()}] [{tag}] {emoji}", style=f"bold {color}")
    body = Text(message, style=color)

    if detail:
        _console.print(header, body)
        _console.print(Text(f"         {detail}", style="dim"))
    else:
        _console.print(header, body)


def trace_plan(goal: str, actions: list[dict]) -> None:
    """Pretty-print an ActionPlan as a table."""
    if not cfg.TRACE_TO_CONSOLE:
        return
    table = Table(
        title=f"📋 Action Plan: {goal}",
        box=box.ROUNDED,
        show_lines=True,
        style="yellow",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Action", style="green")
    table.add_column("Target", style="cyan")
    table.add_column("Value", style="magenta")
    table.add_column("Reason", style="white")

    for a in actions:
        table.add_row(
            str(a.get("id", "?")),
            a.get("action", ""),
            a.get("target", "")[:40],
            str(a.get("value") or "")[:30],
            a.get("reason", "")[:60],
        )
    _console.print(table)


def trace_page_state(url: str, title: str, env: str, buttons: list[str]) -> None:
    if not cfg.TRACE_TO_CONSOLE:
        return
    panel_text = (
        f"[cyan]URL:[/cyan] {url}\n"
        f"[cyan]Title:[/cyan] {title}\n"
        f"[cyan]Environment:[/cyan] {env}\n"
        f"[cyan]Buttons:[/cyan] {', '.join(buttons[:8])}"
    )
    _console.print(Panel(panel_text, title="[bold cyan]Browser State[/bold cyan]", border_style="cyan"))


def trace_verify(success: bool, evidence: list[str], discrepancies: list[str]) -> None:
    if not cfg.TRACE_TO_CONSOLE:
        return
    tag = "VERIFY" if success else "VERIFY_FAIL"
    color, emoji = _TAGS[tag]
    lines = []
    for e in evidence[:5]:
        lines.append(f"  [green]✓[/green] {e}")
    for d in discrepancies[:5]:
        lines.append(f"  [red]✗[/red] {d}")
    _console.print(
        Panel(
            "\n".join(lines) or "(no detail)",
            title=f"[{color}]{emoji} Verification: {'PASS' if success else 'FAIL'}[/{color}]",
            border_style=color,
        )
    )


def trace_section_header(title: str) -> None:
    if not cfg.TRACE_TO_CONSOLE:
        return
    _console.rule(f"[bold bright_white]{title}[/bold bright_white]")
