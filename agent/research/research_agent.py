"""
agent/research/research_agent.py

Research Agent — retrieves authoritative Salesforce documentation
when the local page doesn't contain enough information.

Priority:
  1. Salesforce official Help & Training docs
  2. Salesforce Trailhead instructional material
  3. Salesforce Developer documentation

Returns structured ResearchResult dicts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from bs4 import BeautifulSoup


@dataclass
class ResearchResult:
    concept: str
    facts: list[str] = field(default_factory=list)
    configuration_requirements: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "facts": self.facts,
            "configuration_requirements": self.configuration_requirements,
            "constraints": self.constraints,
            "source": self.source,
        }


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Salesforce documentation search endpoints
_SF_HELP_SEARCH = "https://help.salesforce.com/s/search#q={query}&t=AllResults"
_SF_DEVELOPER_SEARCH = "https://developer.salesforce.com/search#q={query}&section=.io-doc"


class ResearchAgent:
    """
    Fetches and parses Salesforce documentation for a given concept.
    Uses aiohttp for async HTTP requests.
    """

    async def research(self, concept: str) -> ResearchResult:
        """
        Attempt to retrieve facts about `concept` from Salesforce sources.
        Falls back gracefully if network is unavailable.
        """
        result = ResearchResult(concept=concept)

        try:
            async with aiohttp.ClientSession(headers=_HEADERS) as session:
                # Try Salesforce Help first
                sf_help = await self._search_sf_help(session, concept)
                if sf_help:
                    result.facts.extend(sf_help["facts"])
                    result.configuration_requirements.extend(sf_help.get("config", []))
                    result.constraints.extend(sf_help.get("constraints", []))
                    result.source = sf_help.get("source", "Salesforce Help")

                # Augment with developer docs if needed
                if len(result.facts) < 3:
                    dev_docs = await self._search_developer_docs(session, concept)
                    if dev_docs:
                        result.facts.extend(dev_docs["facts"])
                        if not result.source:
                            result.source = dev_docs.get("source", "Salesforce Developer Docs")

        except Exception as exc:
            result.facts.append(f"[Research unavailable: {exc}]")

        # Deduplicate
        result.facts = list(dict.fromkeys(result.facts))[:8]
        result.configuration_requirements = list(dict.fromkeys(result.configuration_requirements))[:5]
        result.constraints = list(dict.fromkeys(result.constraints))[:5]

        return result

    async def _search_sf_help(
        self, session: aiohttp.ClientSession, concept: str
    ) -> dict | None:
        """Scrape Salesforce Help search results."""
        try:
            url = f"https://help.salesforce.com/s/search#q={concept.replace(' ', '+')}"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            return self._extract_facts_from_html(html, "Salesforce Help", concept)
        except Exception:
            return None

    async def _search_developer_docs(
        self, session: aiohttp.ClientSession, concept: str
    ) -> dict | None:
        """Scrape Salesforce Developer Docs."""
        try:
            url = f"https://developer.salesforce.com/docs/atlas.en-us.api.meta/api/"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            return self._extract_facts_from_html(html, "Salesforce Developer Docs", concept)
        except Exception:
            return None

    def _extract_facts_from_html(
        self, html: str, source: str, concept: str
    ) -> dict:
        """Parse HTML and extract relevant sentences as facts."""
        soup = BeautifulSoup(html, "lxml")

        # Remove script/style noise
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        # Extract sentences that mention the concept
        concept_lower = concept.lower()
        sentences = re.split(r"(?<=[.!?])\s+", text)
        facts = [
            s.strip() for s in sentences
            if concept_lower in s.lower() and 20 < len(s.strip()) < 300
        ][:6]

        config_keywords = ["navigate to", "go to setup", "click", "select", "enable", "create"]
        config_steps = [
            s.strip() for s in sentences
            if any(kw in s.lower() for kw in config_keywords) and len(s.strip()) < 300
        ][:4]

        constraint_keywords = ["must", "required", "cannot", "only", "note:"]
        constraints = [
            s.strip() for s in sentences
            if any(kw in s.lower() for kw in constraint_keywords) and len(s.strip()) < 300
        ][:4]

        return {
            "facts": facts,
            "config": config_steps,
            "constraints": constraints,
            "source": source,
        }
