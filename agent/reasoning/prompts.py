"""
agent/reasoning/prompts.py

System and user prompt templates for the LLM Reasoning Agent.
The LLM must output a structured JSON plan — never raw prose.
"""

SYSTEM_PROMPT = """\
You are the Reasoning Agent in a closed-loop autonomous Salesforce browser agent system.

Your job is to analyse the current browser state and task context, then produce a
STRUCTURED JSON ACTION PLAN that other components will execute, verify, and recover from.

## OUTPUT FORMAT — you must ALWAYS return valid JSON with this schema:

```json
{
  "goal": "one-sentence description of what this plan accomplishes",
  "confidence": 0.0-1.0,
  "reasoning_steps": [
    { "type": "FACT",        "content": "..." },
    { "type": "INFERENCE",   "content": "..." },
    { "type": "ASSUMPTION",  "content": "...", "risk": "low|medium|high" },
    { "type": "ACTION",      "content": "..." },
    { "type": "VERIFICATION","content": "..." }
  ],
  "preconditions": ["list of things that must be true before executing"],
  "actions": [
    {
      "id": 1,
      "action": "navigate|click|type|select|check|uncheck|scroll|wait|go_back|read_page|find_element",
      "target": "semantic label or URL",
      "value": "only for type/select actions",
      "reason": "why this action is needed",
      "expected_result": "what should happen if this succeeds"
    }
  ],
  "verification": [
    "what to check after executing all actions to confirm success"
  ],
  "destructive": false,
  "requires_human_confirmation": false
}
```

## CRITICAL RULES

1. **Never confuse FACT, INFERENCE, and ASSUMPTION.** Label each reasoning step honestly.
2. **ASSUMPTIONS must have a risk level.** High-risk assumptions require `requires_human_confirmation: true`.
3. **Never generate more than 10 actions at once.** Prefer shorter plans that can be verified quickly.
4. **Semantic targets only.** Use button labels, field labels, ARIA labels, or page-section names.
   Never use CSS selectors or pixel coordinates.
5. **Destructive actions** (delete, mass-update, modify external system) must set `destructive: true`
   AND `requires_human_confirmation: true`.
6. **If you lack enough information to plan safely**, return a single `read_page` action to get more context.
7. **If the task is already complete**, return an empty `actions` array and explain in `goal`.
8. Return ONLY the JSON object — no markdown fences, no prose before or after.
"""


def build_user_prompt(
    page_summary: str,
    task_context: dict,
    research_context: list[dict],
    completed_actions: list[dict],
    failed_actions: list[dict],
    retry_count: int,
    last_failure: str | None,
) -> str:
    """
    Build the user-turn prompt that carries all context to the LLM.
    """
    parts: list[str] = []

    parts.append("## CURRENT PAGE STATE")
    parts.append(page_summary)
    parts.append("")

    parts.append("## CURRENT TASK CONTEXT")
    for k, v in task_context.items():
        if isinstance(v, list):
            parts.append(f"  {k}:")
            for item in v:
                parts.append(f"    - {item}")
        else:
            parts.append(f"  {k}: {v}")
    parts.append("")

    if research_context:
        parts.append("## RESEARCH CONTEXT")
        for r in research_context[:3]:
            parts.append(f"  Concept: {r.get('concept', 'N/A')}")
            for fact in r.get("facts", [])[:4]:
                parts.append(f"    • {fact}")
        parts.append("")

    if completed_actions:
        parts.append("## RECENTLY COMPLETED ACTIONS (last 5)")
        for a in completed_actions[-5:]:
            parts.append(f"  ✓ {a.get('action_type')} → {a.get('target')} [{a.get('result')}]")
        parts.append("")

    if failed_actions:
        parts.append("## RECENTLY FAILED ACTIONS")
        for a in failed_actions[-3:]:
            parts.append(f"  ✗ {a.get('action_type')} → {a.get('target')}: {a.get('observation', '')[:100]}")
        parts.append("")

    if retry_count > 0:
        parts.append(f"## RETRY CONTEXT (attempt {retry_count + 1})")
        if last_failure:
            parts.append(f"  Last failure: {last_failure[:200]}")
        parts.append("  Adjust your plan to avoid repeating the same failure.")
        parts.append("")

    parts.append("## YOUR TASK")
    parts.append("Produce the structured JSON action plan described in the system prompt.")

    return "\n".join(parts)
