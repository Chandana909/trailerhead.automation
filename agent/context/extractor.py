"""
agent/context/extractor.py

Context Extraction Agent.
Derives structured task/module/unit context from a PageState.
Maintains only information relevant to the current task.
"""
from __future__ import annotations

import re
from typing import Any

from agent.perception.page_model import PageState
from agent.state import AgentState


class ContextExtractor:
    """
    Analyses a PageState and updates the AgentState with the current
    task context: module, unit, task description, required concepts,
    entities, configuration requirements, constraints, and success criteria.
    """

    def extract(self, page: PageState, state: AgentState) -> dict[str, Any]:
        """
        Populate task-related fields in `state` and return the task_context dict.
        """
        sf = page.salesforce
        context: dict[str, Any] = {}

        # ── Module / Unit / Task ──────────────────────────────────────────────
        if sf.module_name:
            state.current_module = sf.module_name
        if sf.unit_name:
            state.current_unit = sf.unit_name

        task_desc = sf.task_description or self._extract_task_from_text(page)
        if task_desc:
            state.current_task = task_desc[:200]
            context["task_description"] = task_desc

        # ── Entities & concepts ───────────────────────────────────────────────
        context["salesforce_environment"] = sf.environment
        if sf.current_object:
            context["current_object"] = sf.current_object
        if sf.page_type:
            context["page_type"] = sf.page_type

        required_concepts = self._infer_concepts(page, task_desc or "")
        if required_concepts:
            context["required_concepts"] = required_concepts

        entities = self._infer_entities(page, task_desc or "")
        if entities:
            context["entities_involved"] = entities

        config_requirements = self._infer_config_requirements(page, task_desc or "")
        if config_requirements:
            context["configuration_requirements"] = config_requirements

        constraints = self._infer_constraints(page, task_desc or "")
        if constraints:
            context["constraints"] = constraints

        success_criteria = self._infer_success_criteria(page, task_desc or "")
        if success_criteria:
            context["success_criteria"] = success_criteria

        # ── Progress ──────────────────────────────────────────────────────────
        if sf.progress_pct is not None:
            context["progress_pct"] = sf.progress_pct

        # ── Forms / inputs available ──────────────────────────────────────────
        if page.inputs:
            context["available_inputs"] = [
                {"label": i.label, "type": i.input_type, "required": i.is_required}
                for i in page.inputs[:10]
            ]
        if page.buttons:
            context["available_buttons"] = [b.label for b in page.buttons[:10]]

        # Persist in state
        state.task_context = context
        return context

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_task_from_text(self, page: PageState) -> str | None:
        """
        Fallback: try to find a task description from the page text.
        Looks for challenge blocks, instruction blocks, or the first
        meaningful paragraph.
        """
        # Search for challenge/instruction patterns in raw text
        patterns = [
            r"(?:your task|challenge|your goal|what to do)[:\s]+(.{20,300})",
            r"(?:create|add|configure|enable|set up|update)\s+(?:a|an|the)\s+.{10,200}",
        ]
        for pat in patterns:
            m = re.search(pat, page.visible_text, re.IGNORECASE)
            if m:
                return m.group(0)[:300].strip()

        # Fall back to first paragraph if on a Trailhead-like page
        if page.salesforce.environment == "trailhead" and page.paragraphs:
            return page.paragraphs[0][:300]

        return None

    def _infer_concepts(self, page: PageState, task: str) -> list[str]:
        """Detect Salesforce concepts mentioned in the task or page text."""
        concept_keywords = [
            "object", "field", "record type", "page layout", "profile", "permission",
            "role", "workflow", "process builder", "flow", "apex", "trigger",
            "report", "dashboard", "lead", "opportunity", "account", "contact",
            "campaign", "case", "validation rule", "formula", "lookup", "relationship",
            "picklist", "custom field", "standard field", "tab", "app", "sandbox",
            "deployment", "metadata", "api", "SOQL", "SOSL",
        ]
        combined = (task + " " + page.visible_text[:1000]).lower()
        found = [kw for kw in concept_keywords if kw in combined]
        return list(dict.fromkeys(found))  # deduplicate preserving order

    def _infer_entities(self, page: PageState, task: str) -> list[str]:
        """Standard Salesforce object names mentioned."""
        sf_objects = [
            "Account", "Contact", "Lead", "Opportunity", "Case", "Campaign",
            "Product", "Pricebook", "Task", "Event", "User", "Profile",
            "Permission Set", "Custom Object",
        ]
        combined = task + " " + page.visible_text[:1000]
        return [obj for obj in sf_objects if obj.lower() in combined.lower()]

    def _infer_config_requirements(self, page: PageState, task: str) -> list[str]:
        """Extract explicit config steps from the task text."""
        config_verbs = ["enable", "create", "add", "configure", "set", "assign",
                        "activate", "deactivate", "deploy", "install"]
        requirements: list[str] = []
        for para in page.paragraphs[:10]:
            if any(v in para.lower() for v in config_verbs):
                requirements.append(para[:200])
        return requirements[:5]

    def _infer_constraints(self, page: PageState, task: str) -> list[str]:
        """Constraints / warnings from the page."""
        constraint_keywords = ["must", "required", "only", "cannot", "do not",
                               "warning", "note", "important"]
        combined = task + " " + page.visible_text[:1000]
        constraints: list[str] = []
        for sent in re.split(r"[.!?]", combined):
            if any(kw in sent.lower() for kw in constraint_keywords):
                clean = sent.strip()
                if 10 < len(clean) < 300:
                    constraints.append(clean)
        return constraints[:5]

    def _infer_success_criteria(self, page: PageState, task: str) -> list[str]:
        """Try to identify what "done" looks like for this task."""
        success_patterns = [
            r"when (?:you|the)\s+(.{10,200}?)(?:\.|$)",
            r"(?:you(?:'ve| have) (?:successfully|completed|finished))\s+(.{10,200}?)(?:\.|$)",
            r"(?:the goal is to|to complete this,? you must)\s+(.{10,200}?)(?:\.|$)",
        ]
        criteria: list[str] = []
        for pat in success_patterns:
            for m in re.finditer(pat, page.visible_text[:2000], re.IGNORECASE):
                criteria.append(m.group(0)[:200].strip())
        return criteria[:3]
