"""
tests/test_suite.py

Automated unit test suite for state, context extraction, HUD overlay, and reasoning.
Runs with `python -m unittest discover -s tests`.
"""
import unittest
from agent.state import AgentState, WorkflowStatus, ActionRecord
from agent.perception.page_model import PageState, SalesforceContext, ButtonState, InputState
from agent.context.extractor import ContextExtractor
from agent.perception.hud import HUDOverlay, HUD_CSS


class TestAgentState(unittest.TestCase):
    def test_initial_state(self):
        state = AgentState()
        self.assertEqual(state.workflow_status, WorkflowStatus.DISCOVER)
        self.assertEqual(len(state.completed_actions), 0)
        self.assertEqual(len(state.tasks_completed), 0)

    def test_state_transitions(self):
        state = AgentState()
        state.transition(WorkflowStatus.UNDERSTAND)
        self.assertEqual(state.workflow_status, WorkflowStatus.UNDERSTAND)
        state.transition(WorkflowStatus.PLAN)
        self.assertEqual(state.workflow_status, WorkflowStatus.PLAN)

    def test_record_action(self):
        state = AgentState()
        rec = ActionRecord(
            action_type="click",
            target="Submit",
            value=None,
            observation="Clicked Submit",
            result="success",
        )
        state.record_action(rec)
        self.assertEqual(len(state.completed_actions), 1)
        self.assertEqual(state.completed_actions[0].target, "Submit")

    def test_loop_detection(self):
        state = AgentState()
        task = "Test Task"
        state.compute_hash(task)
        self.assertFalse(state.check_loop())
        state.compute_hash(task)
        self.assertFalse(state.check_loop())
        state.compute_hash(task)
        self.assertTrue(state.check_loop())


class TestContextExtractor(unittest.TestCase):
    def test_context_extraction(self):
        page = PageState(
            url="https://trailhead.salesforce.com/content/learn/modules/data_modeling",
            title="Data Modeling Module",
            headings=["Create a Custom Object"],
            visible_text="Your task: Create a custom Salesforce object called Property__c.",
            buttons=[ButtonState(label="Check Challenge")],
            inputs=[InputState(label="Name", input_type="text")],
            salesforce=SalesforceContext(
                environment="trailhead",
                module_name="Data Modeling",
                unit_name="Objects Intro",
                task_description="Create a custom Salesforce object called Property__c.",
            ),
        )
        state = AgentState()
        extractor = ContextExtractor()
        context = extractor.extract(page, state)

        self.assertEqual(state.current_module, "Data Modeling")
        self.assertEqual(state.current_unit, "Objects Intro")
        self.assertTrue(len(context.get("required_concepts", [])) > 0)


class TestHUDOverlay(unittest.TestCase):
    def test_hud_css_validity(self):
        self.assertIn("#sf-agent-hud", HUD_CSS)
        self.assertIn("#sf-agent-modal", HUD_CSS)
        self.assertIn("z-index: 2147483647", HUD_CSS)


if __name__ == "__main__":
    unittest.main()
