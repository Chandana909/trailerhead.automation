"""
tests/test_perception.py — Phase 1 standalone demo.

Launches a real browser, navigates to Trailhead, and prints a rich
table of the resulting PageState. No LLM required.

Usage:
    python tests/test_perception.py [url]
"""
import asyncio
import sys

from rich.console import Console
from rich.table import Table
from rich import box

# Add project root to path
sys.path.insert(0, __import__("pathlib").Path(__file__).parent.parent.as_posix())

from agent.perception.browser_agent import BrowserAgent

console = Console()


async def main(url: str) -> None:
    console.rule("[bold cyan]Phase 1 — Browser Perception Demo[/bold cyan]")

    async with BrowserAgent() as agent:
        console.print(f"\n[cyan]Navigating to:[/cyan] {url}")
        await agent.navigate(url)

        console.print("[cyan]Taking snapshot...[/cyan]")
        state = await agent.snapshot()

        # ── Summary ──────────────────────────────────────────────────────────
        console.print(f"\n[bold]URL:[/bold] {state.url}")
        console.print(f"[bold]Title:[/bold] {state.title}")
        console.print(f"[bold]Environment:[/bold] {state.salesforce.environment}")
        console.print(f"[bold]Snapshot at:[/bold] {state.snapshot_timestamp}")

        # ── Headings ─────────────────────────────────────────────────────────
        if state.headings:
            t = Table("Headings", box=box.SIMPLE, style="blue")
            for h in state.headings[:10]:
                t.add_row(h)
            console.print(t)

        # ── Buttons ───────────────────────────────────────────────────────────
        if state.buttons:
            t = Table("Buttons", "Type", "Disabled?", box=box.SIMPLE, style="green")
            for b in state.buttons[:15]:
                t.add_row(b.label, b.button_type, str(b.is_disabled))
            console.print(t)

        # ── Inputs ────────────────────────────────────────────────────────────
        if state.inputs:
            t = Table("Input Label", "Type", "Required", box=box.SIMPLE, style="magenta")
            for i in state.inputs[:10]:
                t.add_row(i.label or "(no label)", i.input_type, str(i.is_required))
            console.print(t)

        # ── Alerts / Toasts ───────────────────────────────────────────────────
        if state.alerts or state.toasts:
            t = Table("Level", "Message", box=box.SIMPLE, style="yellow")
            for a in state.alerts + state.toasts:
                t.add_row(a.level, a.message[:100])
            console.print(t)

        # ── Salesforce context ────────────────────────────────────────────────
        sf = state.salesforce
        t = Table("SF Context Key", "Value", box=box.SIMPLE, style="cyan")
        t.add_row("environment",     sf.environment)
        t.add_row("app_name",        sf.app_name or "")
        t.add_row("current_object",  sf.current_object or "")
        t.add_row("page_type",       sf.page_type or "")
        t.add_row("module_name",     sf.module_name or "")
        t.add_row("unit_name",       sf.unit_name or "")
        t.add_row("progress_pct",    str(sf.progress_pct or ""))
        console.print(t)

        console.print("\n[bold green][OK] Phase 1 complete — PageState successfully extracted.[/bold green]\n")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://trailhead.salesforce.com"
    asyncio.run(main(target))
