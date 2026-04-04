import json
import logging
import re
from typing import TYPE_CHECKING

from app.config import Settings
from app.llm.prompts import load_prompt
from app.llm.prompts.builder import build_synthesis_prompt

if TYPE_CHECKING:
    from app.orchestrator.context import AnalysisContext

logger = logging.getLogger(__name__)

# Loaded once at import time — avoids repeated disk reads per request
SYSTEM_PROMPT = load_prompt("system.md")


class LLMError(Exception):
    """Raised when the LLM call fails in a way the caller should handle."""


class LLMClient:
    """
    Wrapper around the Groq SDK.

    Design decisions:
    - All `groq` SDK imports are confined here; the rest of the codebase never
      imports `groq` directly. This makes the SDK optional: if no API key is set,
      the import still succeeds, but _client stays None.
    - Two explicit failure modes: LLMError (recoverable - agent falls back to deterministic synthesis) and hard errors.
    - JSON extraction uses a regex fallback to strip occasional Markdown fences.
    - temperature=0.2 for structured output: low enough for consistent JSON, not zero to avoid repetition on retries.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None

        if settings.llm_available:
            try:
                from groq import AsyncGroq
                self._client = AsyncGroq(
                    api_key=settings.groq_api_key,
                    timeout=settings.llm_timeout,
                )
                logger.info("LLMClient initialised — model: %s", settings.llm_model)
            except ImportError:
                logger.warning("groq package not installed — LLM synthesis disabled")

    @property
    def available(self) -> bool:
        return self._client is not None

    async def synthesize_report(self, context: "AnalysisContext") -> dict:
        """
        Calls the LLM to synthesize narrative report fields from tool data.

        Returns a dict with keys: executive_summary, recommendations, confidence_score.
        The caller (agent._build_report) merges this with structured tool data to
        produce the final MarketReport — LLM never touches the raw numbers.
        """
        if not self.available:
            raise LLMError("No Groq client available (GROQ_API_KEY not set)")

        import groq

        prompt = build_synthesis_prompt(context)

        try:
            response = await self._client.chat.completions.create(
                model=self.settings.llm_model,
                max_tokens=self.settings.llm_max_tokens,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
        except groq.APIStatusError as exc:
            raise LLMError(f"Groq API error {exc.status_code}: {exc.message}") from exc
        except groq.APITimeoutError as exc:
            raise LLMError("LLM request timed out") from exc
        except groq.APIConnectionError as exc:
            raise LLMError(f"LLM connection error: {exc}") from exc

        raw = response.choices[0].message.content
        return self._parse_response(raw)

    def _parse_response(self, raw: str) -> dict:
        """
        Extract and validate the JSON block from the LLM response.
        Strips Markdown fences defensively — even well-instructed models
        occasionally wrap output in ```json blocks.
        """
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`")

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("LLM returned non-JSON response (first 200 chars): %s", raw[:200])
            raise LLMError(f"Failed to parse LLM JSON response: {exc}") from exc
