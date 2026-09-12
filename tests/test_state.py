"""
tests/test_state.py — Phase 2 standalone demo.

Runs perception → context extraction → prints structured AgentState.
No LLM required.

Usage:
    python tests/test_state.py [url]
"""
import asyncio
import json
import sys

from rich.console import Console
from rich.syntax import Syntax

sys.path.insert(0, __import__("pathlib").Path(__file__).parent.parent.as_posix())

from agent.perception.browser_agent import BrowserAgent
from agent.context.extractor import ContextExtractor
from agent.state import AgentState

console = Console()


async def main(url: str) -> None:
    console.rule("[bold blue]Phase 2 — Structured State Demo[/bold blue]")

    async with BrowserAgent() as agent:
        await agent.navigate(url)
        page = await agent.snapshot()

        state = AgentState()
        extractor = ContextExtractor()
        context = extractor.extract(page, state)

        console.print(f"\n[bold]Session ID:[/bold] {state.session_id}")
        console.print(f"[bold]Workflow Status:[/bold] {state.workflow_status.value}")
        console.print(f"[bold]Module:[/bold] {state.current_module or 'N/A'}")
        console.print(f"[bold]Unit:[/bold] {state.current_unit or 'N/A'}")
        console.print(f"[bold]Task:[/bold] {state.current_task or 'N/A'}")

        console.print("\n[bold cyan]Task Context:[/bold cyan]")
        console.print(Syntax(json.dumps(context, indent=2, default=str), "json", theme="monokai"))

        console.print("\n[bold green][OK] Phase 2 complete — AgentState and task context extracted.[/bold green]\n")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://trailhead.salesforce.com"
    asyncio.run(main(target))
