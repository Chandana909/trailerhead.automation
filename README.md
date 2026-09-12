# 🤖 Salesforce Autonomous Browser Agent

A closed-loop, multi-agent system that autonomously operates Salesforce Trailhead and sandbox workflows with minimal human interaction.

---

## Architecture

```
Perception Agent  →  Context Extractor  →  Research Agent
                                    ↓
                          Reasoning Agent (Groq LLM)
                                    ↓
                            Action Agent (Playwright)
                                    ↓
                         Verification Agent  ←→  Recovery Agent
                                    ↓
                            Memory Manager (SQLite)
                                    ↓
                              Orchestrator (State Machine)
```

The core loop: **OBSERVE → UNDERSTAND → RESEARCH → PLAN → EXECUTE → VERIFY → RECOVER → REPEAT**

---

## Quick Start

### 1. Install dependencies

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m playwright install chromium
```

### 2. Configure credentials

Copy `.env.example` to `.env` and fill in:

```ini
SALESFORCE_USER=your_trailhead_email@example.com
SALESFORCE_PASS=your_trailhead_password
GROQ_API_KEY=gsk_...   # Free at https://console.groq.com
```

### 3. Run phase demos (no LLM needed for Phase 1-2)

```powershell
# Phase 1 — Browser Perception
py -3 tests/test_perception.py

# Phase 2 — Structured State
py -3 tests/test_state.py

# Phase 3 — LLM Reasoning (needs GROQ_API_KEY)
py -3 tests/test_reasoning.py
```

### 4. Run the full autonomous agent

```powershell
py -3 main.py --url "https://trailhead.salesforce.com/content/learn/modules/data_modeling"
```

---

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--url URL` | `.env` value | Starting Salesforce/Trailhead URL |
| `--headless` | off | Run browser headlessly |
| `--autonomous` | `.env` value | Enable autonomous mode |
| `--log-level LEVEL` | INFO | DEBUG / INFO / WARNING / ERROR |

---

## File Structure

```
cheaters/
├── main.py                    # Entry point
├── config.py                  # Typed config from .env
├── requirements.txt
├── .env.example               # Copy to .env
│
├── agent/
│   ├── orchestrator.py        # State machine (8-phase loop)
│   ├── state.py               # AgentState + WorkflowStatus enum
│   ├── perception/            # Browser -> PageState (Playwright)
│   ├── context/               # PageState -> task context
│   ├── research/              # Salesforce docs fetcher
│   ├── reasoning/             # Groq LLM -> ActionPlan
│   ├── actions/               # ActionPlan -> Playwright calls
│   ├── verification/          # Post-action state verification
│   ├── recovery/              # Failure classification + replan
│   └── memory/                # Short-term + SQLite long-term
│
├── observability/
│   ├── tracer.py              # Rich live trace
│   └── logger.py              # JSONL structured log
│
└── tests/
    ├── test_perception.py     # Phase 1 demo
    ├── test_state.py          # Phase 2 demo
    └── test_reasoning.py      # Phase 3 demo
```

---

## Safety

- Destructive actions always require explicit human confirmation
- Bounded retries (max 3 per action)
- Loop detection via state hash
- Full state saved on unrecoverable failure
"# trailerhead.automation" 
