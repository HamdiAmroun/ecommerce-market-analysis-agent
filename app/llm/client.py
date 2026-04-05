import json
import logging
import re
from typing import TYPE_CHECKING

from app.config import Settings
from app.llm.prompts import load_prompt
from app.llm.prompts.builder import build_deep_synthesis_prompt, build_synthesis_prompt

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

    async def synthesize_report(
        self,
        context: "AnalysisContext",
        deep: bool = False,
        competitive_context: str = "",
    ) -> dict:
        """
        Calls the LLM to synthesize narrative report fields from tool data.

        In standard mode: returns executive_summary, recommendations, confidence_score.
        In deep mode: additionally returns a deep_analysis block with key_risks,
        market_opportunities, and enriched_recommendations (priority + rationale).

        The caller (agent._build_report) merges this with structured tool data —
        the LLM never touches the raw numbers, only writes narrative.
        """
        if not self.available:
            raise LLMError("No Groq client available (GROQ_API_KEY not set)")

        import groq

        if deep:
            prompt = build_deep_synthesis_prompt(context, competitive_context=competitive_context)
            max_tokens = self.settings.llm_max_tokens * 2  # deep mode needs more tokens
        else:
            prompt = build_synthesis_prompt(context)
            max_tokens = self.settings.llm_max_tokens

        try:
            response = await self._client.chat.completions.create(
                model=self.settings.llm_model,
                max_tokens=max_tokens,
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

    async def extract_competitive_signals(self, context: "AnalysisContext") -> str:
        """
        Intermediate LLM pass used exclusively in deep mode.

        Makes a short, focused call using only product and competitor data (before
        sentiment and trend are available) to extract the 2-3 most important
        competitive dynamics. The result is a plain-text string that gets injected
        into the final deep synthesis prompt as pre-extracted context.

        Keeping this as a separate call means the final synthesis prompt is informed
        by structured pre-reasoning rather than having to derive everything in one pass.
        Returns an empty string on failure — the main synthesis continues regardless.
        """
        if not self.available:
            return ""

        import groq

        product = context.get_tool_data("product_collector") or {}
        if not product:
            return ""

        name = context.request.product_name
        avg_price = product.get("average_price", 0)
        position = product.get("market_position", "mid-range")
        competitors = product.get("competitors", [])
        comp_lines = "\n".join(
            f"  - {c['name']}: ${c['price']:.2f}"
            + (f" ({c['market_share_pct']}% share)" if c.get("market_share_pct") else "")
            for c in competitors[:3]
        )

        signal_prompt = (
            f"Product: {name} | Price: ${avg_price:.2f} | Position: {position}\n"
            f"Competitors:\n{comp_lines}\n\n"
            "In 2-3 concise sentences, identify the most important competitive dynamics "
            "for this product: pricing pressure, differentiation gaps, or market share risks. "
            "Be specific and data-driven. No generic statements."
        )

        try:
            response = await self._client.chat.completions.create(
                model=self.settings.llm_model,
                max_tokens=150,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": "You are a competitive intelligence analyst. Be concise and specific."},
                    {"role": "user", "content": signal_prompt},
                ],
            )
            return response.choices[0].message.content.strip()
        except (groq.APIStatusError, groq.APITimeoutError, groq.APIConnectionError) as exc:
            logger.warning("Competitive signal extraction failed (non-fatal): %s", exc)
            return ""

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
