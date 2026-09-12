"""
main.py — Entry point for the Salesforce Autonomous Browser Agent.

Usage:
    python main.py [options]

Options:
    --url URL          Starting URL (default: SALESFORCE_URL from .env)
    --headless         Run browser in headless mode
    --autonomous       Override AUTONOMOUS_MODE=true
    --log-level LEVEL  Logging level (DEBUG|INFO|WARNING|ERROR)
    --help             Show this help message
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make sure project root is on the path
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel

console = Console(safe_box=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Salesforce Autonomous Browser Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--url",        type=str, default=None, help="Starting URL")
    parser.add_argument("--headless",   action="store_true",    help="Headless browser mode")
    parser.add_argument("--autonomous", action="store_true",    help="Enable autonomous mode")
    parser.add_argument("--log-level",  type=str, default=None, help="Log level")
    return parser.parse_args()


def prompt_for_url_gui() -> str | None:
    """Display a GUI popup input message box asking the user to paste the Trailhead URL."""
    try:
        import tkinter as tk
        from tkinter import simpledialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        url = simpledialog.askstring(
            title="🎯 Trailhead Autonomous Agent",
            prompt="Please paste the Trailhead module or trail URL you want to complete:",
            initialvalue="https://trailhead.salesforce.com/content/learn/modules/",
        )
        root.destroy()
        return url.strip() if url and url.strip() else None
    except Exception:
        return None


async def _run(args: argparse.Namespace) -> None:
    # If no URL specified on CLI, ask user with a popup message box
    if not args.url:
        pasted_url = prompt_for_url_gui()
        if pasted_url:
            args.url = pasted_url
    # Apply CLI overrides BEFORE importing config-dependent modules
    import os
    if args.headless:
        os.environ["HEADLESS"] = "true"
    if args.autonomous:
        os.environ["AUTONOMOUS_MODE"] = "true"
    if args.log_level:
        os.environ["LOG_LEVEL"] = args.log_level.upper()

    # Late imports so env overrides are picked up
    from config import cfg
    from agent.orchestrator import Orchestrator
    from observability.tracer import trace

    # Validate config
    warnings = cfg.validate()
    for w in warnings:
        console.print(f"[yellow]WARNING: {w}[/yellow]")

    if not cfg.SALESFORCE_USER:
        console.print(
            Panel(
                "[yellow]SALESFORCE_USER is not set in .env.[/yellow]\n"
                "You can log in manually in the opened browser window when requested.",
                title="Configuration Notice",
                border_style="yellow",
            )
        )

    if cfg.LLM_PROVIDER == "groq" and not cfg.GROQ_API_KEY:
        console.print(
            Panel(
                "[red]GROQ_API_KEY is not set.[/red]\n"
                "Get a free key at [cyan]https://console.groq.com[/cyan] and add it to your .env file.",
                title="LLM Configuration Error",
                border_style="red",
            )
        )
        sys.exit(1)

    console.print(
        Panel(
            f"[green]Session starting...[/green]\n"
            f"[cyan]Target:[/cyan] {args.url or cfg.SALESFORCE_URL}\n"
            f"[cyan]Model:[/cyan] {cfg.GROQ_MODEL}\n"
            f"[cyan]Autonomous:[/cyan] {cfg.AUTONOMOUS_MODE}\n"
            f"[cyan]Headless:[/cyan] {cfg.HEADLESS}\n"
            f"[cyan]Logs:[/cyan] {cfg.LOG_DIR}",
            title="[bold green][Agent] Salesforce Autonomous Agent[/bold green]",
            border_style="green",
        )
    )

    async with Orchestrator() as orch:
        final_state = await orch.run(start_url=args.url)

    # Summary
    console.print(
        Panel(
            f"[bold]Status:[/bold] {final_state.workflow_status.value}\n"
            f"[bold]Tasks completed:[/bold] {len(final_state.tasks_completed)}\n"
            f"[bold]Tasks failed:[/bold] {len(final_state.tasks_failed)}\n"
            f"[bold]Actions executed:[/bold] {len(final_state.completed_actions)}\n"
            f"[bold]Session ID:[/bold] {final_state.session_id}",
            title="[bold]Session Complete[/bold]",
            border_style="bright_green" if final_state.workflow_status.value == "COMPLETE" else "red",
        )
    )


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
