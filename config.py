# ─────────────────────────────────────────────────────────────────────────────
# config.py — Central configuration loader
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (the directory containing this file)
_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env", override=False)


class Config:
    """Typed configuration object built from environment variables."""

    # ── Salesforce ────────────────────────────────────────────────────────────
    SALESFORCE_URL: str = os.getenv("SALESFORCE_URL", "https://trailhead.salesforce.com")
    SALESFORCE_USER: str = os.getenv("SALESFORCE_USER", "")
    SALESFORCE_PASS: str = os.getenv("SALESFORCE_PASS", "")

    SALESFORCE_DEV_URL: str = os.getenv("SALESFORCE_DEV_URL", "https://login.salesforce.com")
    SALESFORCE_DEV_USER: str = os.getenv("SALESFORCE_DEV_USER", "")
    SALESFORCE_DEV_PASS: str = os.getenv("SALESFORCE_DEV_PASS", "")

    # ── LLM / Groq ────────────────────────────────────────────────────────────
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "groq")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # ── Agent behaviour ───────────────────────────────────────────────────────
    AUTONOMOUS_MODE: bool = os.getenv("AUTONOMOUS_MODE", "true").lower() == "true"
    HEADLESS: bool = os.getenv("HEADLESS", "false").lower() == "true"
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    ACTION_TIMEOUT_MS: int = int(os.getenv("ACTION_TIMEOUT_MS", "15000"))
    NAVIGATION_TIMEOUT_MS: int = int(os.getenv("NAVIGATION_TIMEOUT_MS", "30000"))

    # ── Observability ─────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: Path = _ROOT / os.getenv("LOG_DIR", "logs")
    TRACE_TO_CONSOLE: bool = os.getenv("TRACE_TO_CONSOLE", "true").lower() == "true"

    # ── Memory ────────────────────────────────────────────────────────────────
    MEMORY_DB_PATH: Path = _ROOT / os.getenv("MEMORY_DB_PATH", "memory.db")

    # ── Safety gates ──────────────────────────────────────────────────────────
    # These action types ALWAYS require human confirmation, even in AUTONOMOUS_MODE.
    DESTRUCTIVE_ACTIONS: frozenset[str] = frozenset({
        "delete_record",
        "delete_field",
        "delete_object",
        "delete_config",
        "modify_external_system",
        "change_credentials",
        "mass_update",
    })

    @classmethod
    def validate(cls) -> list[str]:
        """Return a list of validation warnings. Caller decides how to handle."""
        warnings: list[str] = []
        if not cls.SALESFORCE_USER:
            warnings.append("SALESFORCE_USER is not set.")
        if not cls.SALESFORCE_PASS:
            warnings.append("SALESFORCE_PASS is not set (OK if using email OTP login).")
        if cls.LLM_PROVIDER == "groq" and not cls.GROQ_API_KEY:
            warnings.append("GROQ_API_KEY is not set — LLM reasoning will fail.")
        cls.LOG_DIR.mkdir(parents=True, exist_ok=True)
        return warnings


cfg = Config()
