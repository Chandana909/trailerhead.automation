"""
agent/orchestrator.py

Main Orchestrator — the state machine that drives the full
OBSERVE → UNDERSTAND → RESEARCH → PLAN → EXECUTE → VERIFY → RECOVER loop.

This is the top-level controller. It coordinates all agents and
maintains the AgentState as the single source of truth.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from config import cfg
from agent.state import AgentState, ActionRecord, WorkflowStatus
from agent.perception.browser_agent import BrowserAgent
from agent.perception.page_model import PageState
from agent.context.extractor import ContextExtractor
from agent.research.research_agent import ResearchAgent
from agent.reasoning.reasoning_agent import ReasoningAgent, ActionPlan
from agent.actions.action_agent import ActionAgent, ActionObservation
from agent.verification.verifier import Verifier
from agent.recovery.recovery_agent import RecoveryAgent
from agent.memory.memory_manager import MemoryManager
from observability.tracer import (
    trace, trace_plan, trace_page_state, trace_verify, trace_section_header
)
from observability.logger import AgentLogger


class Orchestrator:
    """
    Autonomous multi-task orchestrator.

    Lifecycle:
        async with Orchestrator() as orch:
            await orch.run(start_url="https://trailhead.salesforce.com/...")
    """

    def __init__(self) -> None:
        self._state = AgentState()
        self._browser = BrowserAgent()
        self._extractor = ContextExtractor()
        self._researcher = ResearchAgent()
        self._reasoner = ReasoningAgent()
        self._verifier: Verifier | None = None
        self._action_agent: ActionAgent | None = None
        self._recovery = RecoveryAgent(max_retries=cfg.MAX_RETRIES)
        self._memory = MemoryManager()
        self._logger = AgentLogger(self._state.session_id)
        self._current_plan: ActionPlan | None = None

    async def __aenter__(self) -> "Orchestrator":
        self._memory.open()
        await self._browser.launch()
        self._verifier = Verifier(self._browser)
        self._action_agent = ActionAgent(self._browser)
        return self

    async def __aexit__(self, *_) -> None:
        self._memory.close()
        await self._browser.close()
        self._logger.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────────────

    async def run(self, start_url: str | None = None) -> AgentState:
        """
        Main agent loop. Runs until workflow is COMPLETE or FAILED.
        """
        trace_section_header(f"Salesforce Autonomous Agent — Session {self._state.session_id}")
        self._logger.log("INIT", extra={"session_id": self._state.session_id})

        if start_url:
            trace("OBSERVE", f"Navigating to start URL: {start_url}")
            await self._browser.navigate(start_url)
        elif cfg.SALESFORCE_URL:
            trace("OBSERVE", f"Navigating to configured URL: {cfg.SALESFORCE_URL}")
            await self._browser.navigate(cfg.SALESFORCE_URL)

        max_iterations = 200  # Safety cap — prevents infinite loops
        iteration = 0

        while (
            self._state.workflow_status not in (WorkflowStatus.COMPLETE, WorkflowStatus.FAILED)
            and iteration < max_iterations
        ):
            iteration += 1
            trace_section_header(f"Loop #{iteration} — {self._state.workflow_status.value}")

            try:
                await self._tick()
            except KeyboardInterrupt:
                trace("WARN", "Keyboard interrupt — saving state and exiting.")
                await self._browser.update_hud(
                    "Interrupted by user.", phase="STOPPED", style_type="warn"
                )
                break
            except Exception as exc:
                trace("ERROR", f"Unhandled exception in main loop: {exc}")
                self._logger.log("ERROR", observation=str(exc), result="failure")
                await self._browser.update_hud(
                    f"Error: {exc}", phase="ERROR", style_type="error"
                )
                # One retry at the orchestration level
                if self._state.retry_count >= cfg.MAX_RETRIES:
                    self._state.transition(WorkflowStatus.FAILED)
                else:
                    self._state.retry_count += 1

        # Save final state
        state_path = cfg.LOG_DIR / f"session_{self._state.session_id}.json"
        self._state.save(state_path)
        trace("STATE", f"Final status: {self._state.workflow_status.value}")
        trace("STATE", f"State saved to: {state_path}")

        # Show trial completion modal message box on screen
        is_success = self._state.workflow_status == WorkflowStatus.COMPLETE
        status_str = self._state.workflow_status.value
        modal_title = "🎉 Trail Completed Successfully!" if is_success else "⚠️ Trial Session Ended"
        modal_msg = (
            "The Trailhead trial in the link is completed! The agent has completed the tasks "
            "and execution is now over."
            if is_success
            else "The trial process ended. Please check the session logs for details."
        )
        details_list = [
            f"<strong>Workflow Status:</strong> {status_str}",
            f"<strong>Tasks Completed:</strong> {len(self._state.tasks_completed)}",
            f"<strong>Actions Executed:</strong> {len(self._state.completed_actions)}",
            f"<strong>Session ID:</strong> {self._state.session_id}",
        ]

        await self._browser.update_hud(
            status="Trial completed. Process is over.",
            phase="COMPLETE" if is_success else "FAILED",
            style_type="success" if is_success else "error",
        )
        await self._browser.show_completion_modal(
            title=modal_title,
            status=status_str,
            message=modal_msg,
            details=details_list,
        )

        # Brief delay to allow the user to view the completed on-screen popup
        await asyncio.sleep(5)

        return self._state

    # ─────────────────────────────────────────────────────────────────────────
    # One agent tick
    # ─────────────────────────────────────────────────────────────────────────

    async def _tick(self) -> None:
        status = self._state.workflow_status

        if status == WorkflowStatus.DISCOVER:
            await self._phase_discover()
        elif status == WorkflowStatus.UNDERSTAND:
            await self._phase_understand()
        elif status == WorkflowStatus.RESEARCH:
            await self._phase_research()
        elif status == WorkflowStatus.PLAN:
            await self._phase_plan()
        elif status == WorkflowStatus.EXECUTE:
            await self._phase_execute()
        elif status == WorkflowStatus.VERIFY:
            await self._phase_verify()
        elif status == WorkflowStatus.RECOVER:
            await self._phase_recover()

    # ─────────────────────────────────────────────────────────────────────────
    # Phase implementations
    # ─────────────────────────────────────────────────────────────────────────

    async def _phase_discover(self) -> None:
        """OBSERVE: Take a snapshot and extract basic page identity."""
        await self._browser.update_hud("Observing page structure...", phase="DISCOVER")
        page = await self._browser.snapshot()
        self._state.current_url = page.url
        self._state.current_page = page.title

        await self._browser.update_hud(
            f"Page: {page.title[:45]}",
            phase="DISCOVER",
            detail=page.url[:60],
        )

        trace("OBSERVE", f"Page: {page.title}", detail=f"URL: {page.url}")
        trace_page_state(
            page.url, page.title,
            page.salesforce.environment,
            [b.label for b in page.buttons[:8]],
        )
        self._logger.log("DISCOVER", observation=page.summary(), result="success")

        # Check for login page
        if self._is_login_page(page):
            trace("OBSERVE", "Login page detected — waiting for user authentication...")
            await self._authenticate(page)
            return

        self._state.transition(WorkflowStatus.UNDERSTAND)

    async def _phase_understand(self) -> None:
        """INTERPRET: Extract task context from the current page."""
        await self._browser.update_hud("Analyzing task requirements & Trailhead page...", phase="UNDERSTAND")
        page = await self._browser.snapshot()
        context = self._extractor.extract(page, self._state)

        # Check for module completion or badge earned on page
        text_lower = page.visible_text.lower()
        if any(kw in text_lower for kw in ["badge earned", "module complete", "congratulations! you earned", "100% complete"]) or (page.salesforce.progress_pct == 100):
            trace("STATE", "🎉 Module complete / Badge earned detected!")
            self._state.transition(WorkflowStatus.COMPLETE)
            return

        task_desc = self._state.current_task or 'Analyzing requirements...'
        await self._browser.update_hud(f"Task: {task_desc[:50]}", phase="UNDERSTAND", detail=f"Module: {self._state.current_module or 'N/A'}")

        trace("UNDERSTAND", f"Task: {self._state.current_task or 'Not yet identified'}")
        trace("UNDERSTAND", f"Module: {self._state.current_module or 'N/A'} / Unit: {self._state.current_unit or 'N/A'}")
        self._logger.log("UNDERSTAND", action="extract_context", observation=str(context), result="success")

        # Decide if we need research
        concepts = context.get("required_concepts", [])
        needs_research = bool(concepts) and len(self._state.research_context) == 0
        self._state.transition(WorkflowStatus.RESEARCH if needs_research else WorkflowStatus.PLAN)

    async def _phase_research(self) -> None:
        """RESEARCH: Fetch Salesforce docs for required concepts."""
        concepts = self._state.task_context.get("required_concepts", [])
        trace("RESEARCH", f"Looking up {len(concepts)} concept(s): {', '.join(concepts[:5])}")

        research_results = []
        for concept in concepts[:3]:  # Cap to avoid flooding
            await self._browser.update_hud(f"Looking up docs: {concept}", phase="RESEARCH")
            trace("RESEARCH", f"Fetching docs for: {concept}")
            result = await self._researcher.research(concept)
            research_results.append(result.to_dict())
            self._logger.log("RESEARCH", action=f"research:{concept}",
                             observation=f"{len(result.facts)} facts found", result="success")

        self._state.research_context = research_results
        trace("RESEARCH", f"Research complete. {len(research_results)} results stored.")
        self._state.transition(WorkflowStatus.PLAN)

    async def _phase_plan(self) -> None:
        """PLAN: Send context to LLM and generate ActionPlan."""
        await self._browser.update_hud("Generating step-by-step action plan with LLM...", phase="PLAN")
        page = await self._browser.snapshot()
        trace("REASON", "Sending context to LLM...")

        # Loop detection
        self._state.compute_hash(self._state.current_task)
        if self._state.check_loop():
            if len(self._state.tasks_completed) > 0:
                trace("STATE", "Loop detected on completed page state — workflow is COMPLETE.")
                self._state.transition(WorkflowStatus.COMPLETE)
                return
            trace("WARN", "Loop detected! Same state seen multiple times — forcing recovery.")
            self._state.loop_detected = True
            self._state.transition(WorkflowStatus.RECOVER)
            return

        try:
            plan = self._reasoner.plan(page, self._state)
        except Exception as exc:
            trace("ERROR", f"LLM planning failed: {exc}")
            self._logger.log("PLAN", observation=str(exc), result="failure")
            self._state.retry_count += 1
            if self._state.retry_count >= cfg.MAX_RETRIES:
                self._state.transition(WorkflowStatus.FAILED)
            return

        self._current_plan = plan
        self._state.action_plan = [a.__dict__ for a in plan.actions]

        await self._browser.update_hud(
            f"Plan: {plan.goal[:50]}",
            phase="PLAN",
            detail=f"{len(plan.actions)} action(s) planned",
        )

        trace("REASON", f"Plan goal: {plan.goal}", detail=f"Confidence: {plan.confidence:.0%}, Actions: {len(plan.actions)}")
        trace_plan(plan.goal, [a.__dict__ for a in plan.actions])

        # Log reasoning steps
        for step in plan.reasoning_steps[:5]:
            trace("REASON", f"[{step.get('type','?')}] {step.get('content','')[:120]}")

        self._logger.log("PLAN", action=plan.goal,
                         observation=f"{len(plan.actions)} actions planned",
                         result="success", extra={"plan": plan.to_dict()})

        # Safety gate for destructive plans
        if plan.requires_human_confirmation:
            confirmed = await self._request_human_confirmation(plan)
            if not confirmed:
                trace("WARN", "Human rejected plan. Stopping.")
                self._state.transition(WorkflowStatus.FAILED)
                return

        if not plan.actions:
            trace("STATE", "Plan has no actions — task may already be complete.")
            self._state.transition(WorkflowStatus.COMPLETE)
            return

        self._state.transition(WorkflowStatus.EXECUTE)

    async def _phase_execute(self) -> None:
        """ACT: Execute the next action in the plan, one at a time."""
        if not self._current_plan or not self._current_plan.actions:
            self._state.transition(WorkflowStatus.VERIFY)
            return

        # Execute ONE action and observe
        action = self._current_plan.actions.pop(0)
        self._state.action_plan = [a.__dict__ for a in self._current_plan.actions]

        await self._browser.update_hud(
            f"Action: {action.action}({action.target})",
            phase="EXECUTE",
            detail=action.reason or "",
        )

        trace("ACTION", f"{action.action}({action.target!r}, {action.value!r})", detail=action.reason)
        assert self._action_agent is not None
        observation = await self._action_agent.execute(action)
        trace("OBSERVE", observation.observation[:200])
        self._logger.log(
            "EXECUTE",
            action=f"{action.action}:{action.target}",
            observation=observation.observation,
            result=observation.result,
        )

        # Update state
        rec = ActionRecord(
            action_type=action.action,
            target=action.target,
            value=action.value,
            observation=observation.observation,
            result=observation.result,
            failure_category=observation.failure_category,
        )
        self._state.record_action(rec)
        self._state.record_observation(observation.observation)

        if observation.new_url:
            self._state.current_url = observation.new_url

        if observation.result == "failure":
            # Immediately move to recovery
            self._state.transition(WorkflowStatus.RECOVER)
            return

        # After action, verify then continue executing or move to final verify
        if not self._current_plan.actions:
            self._state.transition(WorkflowStatus.VERIFY)
        # else stay in EXECUTE for next action

    async def _phase_verify(self) -> None:
        """VERIFY: Confirm the overall task succeeded."""
        await self._browser.update_hud("Verifying task completion & success criteria...", phase="VERIFY")
        page = await self._browser.snapshot()
        success_criteria = self._state.task_context.get("success_criteria", [])

        assert self._verifier is not None
        result = await self._verifier.verify_task_complete(success_criteria)
        trace_verify(result.success, result.evidence, result.discrepancies)
        self._state.record_verification(self._verifier.to_state_record(result))
        self._logger.log(
            "VERIFY",
            observation=f"Success: {result.success}",
            result="success" if result.success else "failure",
            extra={"evidence": result.evidence, "discrepancies": result.discrepancies},
        )

        if result.success or not success_criteria:
            task = self._state.current_task
            self._state.tasks_completed.append(task)
            trace("STATE", f"Task complete: {task}")
            trace("NEXT", "Detecting next task...")
            await self._browser.update_hud(f"Task completed: {task}", phase="VERIFY", style_type="success")
            self._state.research_context = []  # Clear for next task
            self._state.retry_count = 0
            self._state.transition(WorkflowStatus.DISCOVER)
        else:
            trace("VERIFY_FAIL", "Verification failed — replanning.")
            await self._browser.update_hud("Verification failed — initiating recovery...", phase="VERIFY", style_type="warn")
            self._state.transition(WorkflowStatus.RECOVER)

    async def _phase_recover(self) -> None:
        """RECOVER: Classify failure, build recovery plan, re-enter loop."""
        await self._browser.update_hud("Recovering from execution step issue...", phase="RECOVER", style_type="warn")
        page = await self._browser.snapshot()

        # Get the most recent failed action observation
        last_failed = self._state.failed_actions[-1] if self._state.failed_actions else None
        if last_failed:
            from agent.actions.action_agent import ActionObservation
            obs = ActionObservation(
                action=last_failed.action_type,
                target=last_failed.target,
                value=last_failed.value,
                result="failure",
                observation=last_failed.observation,
                failure_category=last_failed.failure_category,
            )
            recovery_plan = self._recovery.classify_and_plan(obs, self._state, page)
        else:
            # Verification-level recovery — no specific failed action
            from agent.state import FailureCategory
            from agent.actions.action_agent import ActionObservation
            obs = ActionObservation("verify", "", None, "failure", "Verification failed")
            recovery_plan = self._recovery.classify_and_plan(obs, self._state, page)

        trace("RECOVER", f"Strategy: {recovery_plan.strategy}", detail=recovery_plan.replan_hint[:200])
        self._logger.log("RECOVER", action=recovery_plan.strategy,
                         observation=recovery_plan.replan_hint, result="recovery")

        if recovery_plan.abort:
            trace("ERROR", f"Cannot recover: {recovery_plan.replan_hint}")
            self._state.tasks_failed.append(self._state.current_task)
            self._state.transition(WorkflowStatus.FAILED)
            return

        # Inject recovery context into next plan
        self._state.task_context["recovery_hint"] = recovery_plan.replan_hint
        self._state.task_context["failure_category"] = recovery_plan.failure_category.value

        # Execute precondition actions from the recovery plan
        if recovery_plan.precondition_actions and self._action_agent:
            for pre_action_dict in recovery_plan.precondition_actions:
                from agent.reasoning.reasoning_agent import PlannedAction
                pre = PlannedAction(
                    id=0,
                    action=pre_action_dict.get("action", "read_page"),
                    target=pre_action_dict.get("target", ""),
                    value=pre_action_dict.get("value"),
                    reason=pre_action_dict.get("reason", "recovery precondition"),
                )
                pre_obs = await self._action_agent.execute(pre)
                trace("RECOVER", f"Precondition: {pre.action}({pre.target}) → {pre_obs.result}")

        # Re-plan from scratch
        self._current_plan = None
        self._state.action_plan = []
        self._state.transition(WorkflowStatus.PLAN)

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _is_login_page(self, page: PageState) -> bool:
        text = page.visible_text.lower()
        url = page.url.lower()
        
        if "login" in url or "auth" in url:
            return True
            
        has_login_keywords = any(
            kw in text for kw in ("username", "password", "log in", "sign in", "check your email", "verification code")
        )
        has_login_input = any(
            i.input_type == "password" or (i.label and "email" in i.label.lower()) or (i.label and "code" in i.label.lower()) for i in page.inputs
        )
        return has_login_keywords and has_login_input

    async def _authenticate(self, page: PageState) -> None:
        """
        Supports manual login in the browser window with an on-screen HUD prompt
        and automatic login completion detection.
        """
        trace("WARN", "🔑 Authentication required. Please complete login in the opened browser window.")
        await self._browser.update_hud(
            status="🔑 Manual Login Required: Please log in to Trailhead in this window.",
            phase="AUTH_REQUIRED",
            detail="The agent will automatically detect when login completes and start!",
            style_type="warn",
        )

        # Poll until the user completes login in the browser window
        max_auth_wait_seconds = 300  # 5 minutes max wait
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < max_auth_wait_seconds:
            await asyncio.sleep(2.5)
            current_page = await self._browser.snapshot()
            if not self._is_login_page(current_page):
                trace("ACTION", "✅ Manual login detected! Resuming agent execution.")
                await self._browser.update_hud(
                    status="✅ Logged in successfully!",
                    phase="AUTH_SUCCESS",
                    detail="Starting autonomous trial execution...",
                    style_type="success",
                )
                await asyncio.sleep(2)
                self._state.transition(WorkflowStatus.DISCOVER)
                return

        trace("ERROR", "Authentication timed out waiting for user login.")
        await self._browser.update_hud(
            status="Authentication timed out.",
            phase="AUTH_FAILED",
            style_type="error",
        )
        self._state.transition(WorkflowStatus.FAILED)

    async def _request_human_confirmation(self, plan: ActionPlan) -> bool:
        """
        Safety gate — always prompt for destructive/high-risk plans.
        In headed mode this is a console prompt.
        """
        trace("WARN", "⚠ HUMAN CONFIRMATION REQUIRED ⚠")
        trace("WARN", f"Plan: {plan.goal}")
        if plan.destructive:
            trace("WARN", "This plan is DESTRUCTIVE. It may delete data or configuration.")
        response = input("\nType 'yes' to proceed, anything else to abort: ").strip().lower()
        return response == "yes"
