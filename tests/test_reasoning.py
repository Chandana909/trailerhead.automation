"""
tests/test_reasoning.py — Phase 3 standalone demo.

Builds a mock task context, sends it to Groq (llama-3.3-70b-versatile),
and prints the resulting ActionPlan. Requires GROQ_API_KEY in .env.

Usage:
    python tests/test_reasoning.py
"""
import asyncio
import json
import sys

from rich.console import Console
from rich.syntax import Syntax
from rich.panel import Panel

sys.path.insert(0, __import__("pathlib").Path(__file__).parent.parent.as_posix())

from agent.state import AgentState
from agent.perception.page_model import PageState, SalesforceContext
from agent.reasoning.reasoning_agent import ReasoningAgent

console = Console()


def _mock_page() -> PageState:
    """A mock Trailhead page for a 'Create a Custom Object' task."""
    from agent.perception.page_model import ButtonState, InputState
    return PageState(
        url="https://trailhead.salesforce.com/content/learn/modules/data_modeling/objects_intro",
        title="Understand Custom & Standard Objects | Salesforce Trailhead",
        headings=["Create a Custom Object", "Step 1 of 3"],
        visible_text=(
            "Your task: Create a custom Salesforce object called 'Property__c' "
            "with the label 'Property' and plural label 'Properties'. "
            "Enable 'Allow Reports' and set the Record Name to 'Property Name' (Text type). "
            "Navigate to Setup > Object Manager > Create > Custom Object to begin."
        ),
        buttons=[
            ButtonState(label="Check Challenge"),
            ButtonState(label="Get Help"),
        ],
        inputs=[],
        salesforce=SalesforceContext(
            environment="trailhead",
            module_name="Data Modeling",
            unit_name="Understand Custom & Standard Objects",
            task_description=(
                "Create a custom object called 'Property__c' with label 'Property', "
                "plural 'Properties', enable Reports, Record Name = 'Property Name' (Text)."
            ),
        ),
    )


def _mock_state() -> AgentState:
    state = AgentState()
    state.task_context = {
        "task_description": (
            "Create a custom Salesforce object called 'Property__c' "
            "with label 'Property', plural label 'Properties'. "
            "Enable Allow Reports. Set Record Name to 'Property Name' (Text type)."
        ),
        "required_concepts": ["custom object", "object manager", "setup"],
        "entities_involved": ["Custom Object"],
        "configuration_requirements": [
            "Navigate to Setup > Object Manager > Create > Custom Object",
            "Set Label to 'Property'",
            "Set Plural Label to 'Properties'",
            "Enable 'Allow Reports'",
            "Set Record Name to 'Property Name', type Text",
            "Click Save",
        ],
        "success_criteria": [
            "Custom object Property__c appears in Object Manager",
            "Salesforce shows 'Saved' confirmation",
        ],
    }
    state.current_module = "Data Modeling"
    state.current_unit = "Understand Custom & Standard Objects"
    state.current_task = "Create custom object Property__c"
    return state


async def main() -> None:
    console.rule("[bold yellow]Phase 3 — LLM Reasoning Demo[/bold yellow]")

    page = _mock_page()
    state = _mock_state()

    console.print("\n[cyan]Sending context to Groq llama-3.3-70b-versatile...[/cyan]")

    agent = ReasoningAgent()
    plan = agent.plan(page, state)

    console.print(Panel(f"[bold green]{plan.goal}[/bold green]", title="Goal", border_style="green"))
    console.print(f"[bold]Confidence:[/bold] {plan.confidence:.0%}")
    console.print(f"[bold]Destructive:[/bold] {plan.destructive}")
    console.print(f"[bold]Requires confirmation:[/bold] {plan.requires_human_confirmation}")

    if plan.reasoning_steps:
        console.print("\n[bold cyan]Reasoning Steps:[/bold cyan]")
        for step in plan.reasoning_steps:
            color = {
                "FACT": "green", "INFERENCE": "yellow", "ASSUMPTION": "orange3",
                "ACTION": "blue", "VERIFICATION": "magenta",
            }.get(step.get("type", ""), "white")
            console.print(f"  [{color}][{step.get('type','?')}][/{color}] {step.get('content','')}")

    console.print("\n[bold cyan]Action Plan:[/bold cyan]")
    console.print(
        Syntax(
            json.dumps([a.__dict__ for a in plan.actions], indent=2, default=str),
            "json",
            theme="monokai",
        )
    )

    if plan.verification:
        console.print("\n[bold cyan]Verification Criteria:[/bold cyan]")
        for v in plan.verification:
            console.print(f"  - {v}")

    console.print("\n[bold green][OK] Phase 3 complete — ActionPlan generated from LLM.[/bold green]\n")


if __name__ == "__main__":
    asyncio.run(main())
