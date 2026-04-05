import asyncio
import logging
import time
from datetime import datetime, timezone

from app.config import Settings
from app.llm.client import LLMClient, LLMError
from app.models.requests import AnalysisRequest
from app.models.responses import (
    CompetitorSummary,
    DeepAnalysisSection,
    EnrichedRecommendation,
    MarketReport,
    MonthlyDataPoint,
    PlatformPrice,
    ProductAnalysisSection,
    ReportMetadata,
    SentimentSection,
    SentimentThemeSummary,
    TrendSection,
)
from app.orchestrator.context import AnalysisContext
from app.orchestrator.executor import ToolExecutor
from app.orchestrator.pipeline import AnalysisPipeline

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Raised when a required pipeline step fails or minimum data is not met."""


class MarketAnalysisAgent:
    """
    The main orchestrator for market analysis.

    Orchestration flow
    ──────────────────
    1. Accept an AnalysisRequest and a job_id.
    2. Create an AnalysisContext (shared blackboard state).
    3. Retrieve the ordered pipeline steps for the requested depth.
    4. Execute each step via ToolExecutor (handles retries and timeouts).
    5. Accumulate results in the context.
       - Required step fails -> raise PipelineError (job marked FAILED)
       - Optional step fails -> record warning, continue
    6. Check context.has_minimum_data (≥2 tools succeeded).
    7. Synthesize the final MarketReport:
       a. Try LLM synthesis -> richer narrative
       b. Fall back to deterministic synthesis -> always works, no API needed
    8. Return the completed context.

    Why this custom orchestrator (not LangGraph/CrewAI)?
    ────────────────────────────────────────────────
    - I wanted to have an explicit control flow that is readable and debuggable without framework magic.
    - And to see the real architecture understanding.
    - Three sequential tools with clear data dependencies don't benefit from
      a graph abstraction; added complexity would obscure the design.
    - Zero framework lock-in; the agent can be extended incrementally.
    """

    def __init__(self, settings: Settings, llm_client: LLMClient) -> None:
        self.settings = settings
        self.llm = llm_client
        self.pipeline = AnalysisPipeline()
        self.executor = ToolExecutor(settings)

    async def run(self, request: AnalysisRequest, job_id: str) -> AnalysisContext:
        start_wall = time.perf_counter()
        context = AnalysisContext(job_id=job_id, request=request)
        steps = self.pipeline.get_steps(request.analysis_depth)

        logger.info(
            "Analysis started | job=%s product=%r depth=%s steps=%d",
            job_id,
            request.product_name,
            request.analysis_depth,
            len(steps),
        )

        # ── Execute pipeline steps ────────────────────────────────────────────
        # Step 0 (ProductCollector) always runs first — its output determines
        # market_position and data_source, which downstream tools read from the
        # blackboard. Once it completes, the remaining steps have no dependency
        # on each other and run concurrently via asyncio.gather.
        first_step = steps[0]
        first_result = await self.executor.run_step(first_step, context)
        context.add_tool_result(first_result)

        if not first_result.success and first_step.required:
            context.completed_at = datetime.now(timezone.utc)
            raise PipelineError(
                f"Required tool '{first_step.tool.name}' failed: {first_result.error}"
            )

        remaining_steps = steps[1:]
        if remaining_steps:
            parallel_results = await asyncio.gather(
                *[self.executor.run_step(step, context) for step in remaining_steps]
            )
            for step, result in zip(remaining_steps, parallel_results):
                context.add_tool_result(result)
                if not result.success and not result.skipped and step.required:
                    context.completed_at = datetime.now(timezone.utc)
                    raise PipelineError(
                        f"Required tool '{step.tool.name}' failed: {result.error}"
                    )
                elif result.skipped:
                    msg = f"Optional tool '{step.tool.name}' skipped: no catalog data found — sentiment omitted"
                    context.warnings.append(msg)
                    logger.info("job=%s %s", job_id, msg)
                elif not result.success:
                    msg = f"Optional tool '{step.tool.name}' failed (continuing): {result.error}"
                    context.warnings.append(msg)
                    logger.warning("job=%s %s", job_id, msg)

        # ── Validate minimum viable data ──────────────────────────────────────
        if not context.has_minimum_data:
            raise PipelineError(
                f"Insufficient data: only {len(context.successful_tool_names)} tool(s) succeeded "
                f"(minimum 2 required). Succeeded: {context.successful_tool_names}"
            )

        # ── Synthesise report ─────────────────────────────────────────────────
        context.report = await self._synthesize_report(context, time.perf_counter() - start_wall)
        context.completed_at = datetime.now(timezone.utc)

        total_ms = (time.perf_counter() - start_wall) * 1000
        logger.info(
            "Analysis completed | job=%s generated_by=%s total=%.0fms",
            job_id,
            context.report.generated_by,
            total_ms,
        )
        return context

    # ── Synthesis ─────────────────────────────────────────────────────────────
    async def _synthesize_report(self, context: AnalysisContext, elapsed_s: float) -> MarketReport:
        """Try LLM synthesis; fall back to deterministic if LLM unavailable or fails.

        Deep mode runs two LLM passes:
          1. extract_competitive_signals() — short focused call on product/competitor
             data only, producing a competitive_context string stored on the context.
          2. synthesize_report() — full synthesis using all tool data plus the
             pre-extracted signals, requesting the richer deep_analysis schema.
        Standard mode is a single synthesis call, unchanged.
        """
        is_deep = context.request.analysis_depth == "deep"

        if self.llm.available:
            try:
                # Pass 1 (deep only): extract intermediate competitive signals
                competitive_context = ""
                if is_deep:
                    competitive_context = await self.llm.extract_competitive_signals(context)

                # Pass 2: full synthesis (deep uses richer prompt + schema)
                llm_data = await self.llm.synthesize_report(
                    context,
                    deep=is_deep,
                    competitive_context=competitive_context,
                )
                return self._build_report(context, llm_data, "llm", elapsed_s)
            except LLMError as exc:
                msg = f"LLM synthesis failed, using deterministic fallback: {exc}"
                context.warnings.append(msg)
                logger.warning("job=%s %s", context.job_id, msg)

        return self._build_report(context, None, "fallback", elapsed_s)

    def _build_report(
        self,
        context: AnalysisContext,
        llm_data: dict | None,
        generated_by: str,
        elapsed_s: float,
    ) -> MarketReport:
        """
        Merge structured tool data (always available) with optional LLM narrative.

        Structured sections (ProductAnalysisSection, SentimentSection, TrendSection) are always built from tool data
         - Never from the LLM, ensuring data accuracy regardless of LLM availability.

        For richer narrative, if LLM is available, use it to populate the:
        executive_summary, recommendations, confidence_score, and key_insights.
        """
        product_section = self._build_product_section(context)
        sentiment_section = self._build_sentiment_section(context)
        trend_section = self._build_trend_section(context)
        metadata = self._build_metadata(context, elapsed_s)

        is_deep = context.request.analysis_depth == "deep"
        deep_analysis: DeepAnalysisSection | None = None

        if llm_data:
            executive_summary = llm_data.get("executive_summary", self._fallback_summary(context))
            recommendations = llm_data.get("recommendations") or self._fallback_recommendations(context)
            confidence_score = float(llm_data.get("confidence_score", 0.75))
            if is_deep and "deep_analysis" in llm_data:
                deep_analysis = self._parse_deep_analysis(llm_data["deep_analysis"])
        else:
            executive_summary = self._fallback_summary(context)
            recommendations = self._fallback_recommendations(context)
            confidence_score = self._calculate_confidence(context)
            if is_deep:
                deep_analysis = self._fallback_deep_analysis(context)

        return MarketReport(
            executive_summary=executive_summary,
            product_analysis=product_section,
            sentiment_analysis=sentiment_section,
            market_trends=trend_section,
            recommendations=recommendations[:7],  # cap per schema
            confidence_score=round(min(1.0, max(0.0, confidence_score)), 3),
            generated_by=generated_by,
            metadata=metadata,
            deep_analysis=deep_analysis,
        )

    # ── Section builders ──────────────────────────────────────────────────────
    def _build_product_section(self, context: AnalysisContext) -> ProductAnalysisSection:
        data = context.get_tool_data("product_collector")
        if not data:
            # Minimal placeholder (shouldn't happen - product_collector is required)
            return ProductAnalysisSection(
                average_price=0.0,
                price_range_min=0.0,
                price_range_max=0.0,
                market_position="mid-range",
                competitor_count=0,
                top_platforms=[],
                top_competitors=[],
            )
        return ProductAnalysisSection(
            average_price=data["average_price"],
            price_range_min=data["price_range_min"],
            price_range_max=data["price_range_max"],
            market_position=data["market_position"],
            competitor_count=len(data.get("competitors", [])),
            top_platforms=[
                PlatformPrice(platform=p["name"], price=p["price"])
                for p in data.get("platforms", [])[:4]
            ],
            top_competitors=[
                CompetitorSummary(
                    name=c["name"],
                    price=c["price"],
                    market_share_pct=c.get("market_share_pct"),
                )
                for c in data.get("competitors", [])[:3]
            ],
        )

    def _build_sentiment_section(self, context: AnalysisContext) -> SentimentSection | None:
        data = context.get_tool_data("sentiment_analyzer")
        if not data:
            return None
        themes = [
            SentimentThemeSummary(
                theme=t["theme"],
                sentiment=t["sentiment"],
                frequency=t["frequency"],
            )
            for t in data.get("themes", [])[:6]
        ]
        reviews = data.get("sample_reviews", [])
        return SentimentSection(
            overall_score=data["overall_score"],
            label=data["label"],
            review_count=data["review_count"],
            top_themes=themes,
            sample_positive=next(
                (r["text"] for r in reviews if r["sentiment"] == "positive"), None
            ),
            sample_negative=next(
                (r["text"] for r in reviews if r["sentiment"] == "negative"), None
            ),
        )

    def _build_trend_section(self, context: AnalysisContext) -> TrendSection:
        data = context.get_tool_data("trend_analyzer")
        if not data:
            return TrendSection(
                trend_direction="stable",
                momentum_score=0.5,
                seasonal_pattern=None,
                search_volume_trend=[],
                price_trend=[],
                forecast_summary="Trend data unavailable.",
            )
        return TrendSection(
            trend_direction=data["trend_direction"],
            momentum_score=data["momentum_score"],
            seasonal_pattern=data.get("seasonal_pattern"),
            search_volume_trend=[
                MonthlyDataPoint(month=p["month"], value=p["value"])
                for p in data.get("search_volume_trend", [])
            ],
            price_trend=[
                MonthlyDataPoint(month=p["month"], value=p["value"])
                for p in data.get("price_trend", [])
            ],
            forecast_summary=data["forecast_summary"],
        )

    def _build_metadata(self, context: AnalysisContext, elapsed_s: float) -> ReportMetadata:
        tool_times = {
            name: round(r.execution_time_ms, 1)
            for name, r in context.tool_results.items()
        }
        succeeded = sum(1 for r in context.tool_results.values() if r.success)
        skipped = sum(1 for r in context.tool_results.values() if r.skipped)
        failed = len(context.tool_results) - succeeded - skipped
        return ReportMetadata(
            tool_execution_ms=tool_times,
            total_execution_ms=round(elapsed_s * 1000, 1),
            tools_succeeded=succeeded,
            tools_failed=failed,
            tools_skipped=skipped,
            warnings=context.warnings,
        )

    # ── Deterministic fallback synthesis ─────────────────────────────────────
    def _fallback_summary(self, context: AnalysisContext) -> str:
        product = context.get_tool_data("product_collector") or {}
        sentiment = context.get_tool_data("sentiment_analyzer") or {}
        trends = context.get_tool_data("trend_analyzer") or {}

        name = context.request.product_name
        category = context.request.category
        price = product.get("average_price", 0)
        position = product.get("market_position", "mid-range")
        n_competitors = len(product.get("competitors", []))
        sent_label = sentiment.get("label", "")
        review_count = sentiment.get("review_count", 0)
        direction = trends.get("trend_direction", "stable")
        momentum = trends.get("momentum_score", 0.5)

        parts = [
            f"{name} is a {position}-positioned product in the {category} market, "
            f"averaging ${price:.2f} across {len(product.get('platforms', []))} platforms.",
        ]
        if n_competitors:
            parts.append(f"It faces {n_competitors} direct competitors.")
        if sent_label and review_count:
            parts.append(
                f"Customer sentiment is {sent_label} based on {review_count:,} reviews."
            )
        if direction:
            parts.append(
                f"Market demand is {direction} with a momentum score of {momentum:.2f}/1.00."
            )

        return " ".join(parts)

    def _fallback_recommendations(self, context: AnalysisContext) -> list[str]:
        product = context.get_tool_data("product_collector") or {}
        sentiment = context.get_tool_data("sentiment_analyzer") or {}
        trends = context.get_tool_data("trend_analyzer") or {}

        recs: list[str] = []
        position = product.get("market_position", "mid-range")
        competitors = product.get("competitors", [])
        neg_themes = [
            t for t in sentiment.get("themes", []) if t["sentiment"] == "negative"
        ]
        direction = trends.get("trend_direction", "stable")
        seasonal = trends.get("seasonal_pattern")

        if position == "premium" and competitors:
            cheapest = min(competitors, key=lambda c: c["price"])
            recs.append(
                f"Strengthen perceived value vs. {cheapest['name']} (${cheapest['price']:.2f}) "
                "through bundled accessories or extended warranty messaging."
            )

        if neg_themes:
            top_neg = neg_themes[0]["theme"]
            recs.append(
                f"Address top negative feedback driver ('{top_neg}') in product page "
                "copy and FAQ to improve conversion rate."
            )

        if direction == "rising":
            recs.append(
                "Capitalise on rising market momentum by increasing paid search bids "
                "and expanding to adjacent customer segments."
            )
        elif direction == "declining":
            recs.append(
                "Mitigate declining trend with promotional pricing or bundle offers "
                "to defend market share."
            )

        if seasonal:
            recs.append(
                f"Plan promotional campaigns around the identified seasonal pattern: {seasonal[:80]}."
            )

        if not recs:
            recs.append("Monitor competitive pricing weekly and adjust positioning as needed.")

        recs.append(
            "Ensure product listing quality (images, title, description) is optimised "
            "across all top-performing platforms to maximise organic visibility."
        )

        return recs[:5]

    def _calculate_confidence(self, context: AnalysisContext) -> float:
        """Heuristic confidence score based on how many tools succeeded."""
        total = len(self.pipeline.get_steps(context.request.analysis_depth))
        succeeded = sum(1 for r in context.tool_results.values() if r.success)
        base = succeeded / max(total, 1)
        # Slight penalty for no LLM synthesis
        return round(base * 0.85, 3)

    # ── Deep mode helpers ─────────────────────────────────────────────────────
    def _parse_deep_analysis(self, raw: dict) -> DeepAnalysisSection | None:
        """Parse LLM deep_analysis block into typed model; returns None on malformed data."""
        try:
            enriched = [
                EnrichedRecommendation(
                    text=r["text"],
                    priority=r.get("priority", "medium"),
                    rationale=r.get("rationale", ""),
                )
                for r in raw.get("enriched_recommendations", [])[:5]
            ]
            return DeepAnalysisSection(
                key_risks=raw.get("key_risks", ["Insufficient data to identify risks"])[:3],
                market_opportunities=raw.get("market_opportunities", ["Insufficient data"])[:3],
                enriched_recommendations=enriched or [
                    EnrichedRecommendation(
                        text="Monitor competitive landscape and adjust pricing accordingly.",
                        priority="medium",
                        rationale="Fallback recommendation — LLM deep_analysis block was incomplete.",
                    )
                ],
            )
        except Exception:
            return None

    def _fallback_deep_analysis(self, context: AnalysisContext) -> DeepAnalysisSection:
        """Deterministic deep analysis section when LLM is unavailable."""
        product = context.get_tool_data("product_collector") or {}
        sentiment = context.get_tool_data("sentiment_analyzer") or {}
        trends = context.get_tool_data("trend_analyzer") or {}

        position = product.get("market_position", "mid-range")
        competitors = product.get("competitors", [])
        direction = trends.get("trend_direction", "stable")
        neg_themes = [t for t in sentiment.get("themes", []) if t["sentiment"] == "negative"]
        momentum = trends.get("momentum_score", 0.5)

        # Key risks
        risks: list[str] = []
        if competitors:
            cheapest = min(competitors, key=lambda c: c["price"])
            risks.append(
                f"Price competition from {cheapest['name']} (${cheapest['price']:.2f}) "
                "could erode market share if value perception weakens."
            )
        if neg_themes:
            risks.append(
                f"Persistent negative sentiment around '{neg_themes[0]['theme']}' "
                "may suppress repeat purchase rate if unaddressed."
            )
        if direction == "declining":
            risks.append("Declining market momentum signals weakening demand — "
                         "risk of inventory build-up without promotional intervention.")
        if not risks:
            risks.append("Competitive intensity in this category remains elevated — "
                         "monitor pricing weekly to avoid positioning drift.")

        # Opportunities
        opportunities: list[str] = []
        if direction == "rising":
            opportunities.append(
                "Rising momentum creates a window to expand distribution channels "
                "and capture share before competitors respond."
            )
        if trends.get("seasonal_pattern"):
            opportunities.append(
                f"Seasonal pattern ({trends['seasonal_pattern'][:60]}...) offers "
                "predictable windows for promotional uplift and inventory pre-positioning."
            )
        if position == "premium" and momentum > 0.65:
            opportunities.append(
                "Strong momentum in the premium segment supports a limited-edition "
                "variant strategy to test price ceiling and drive PR coverage."
            )
        if not opportunities:
            opportunities.append(
                "Stable demand with consistent search volume provides a reliable "
                "baseline for performance marketing optimisation."
            )

        # Enriched recommendations with priority
        enriched: list[EnrichedRecommendation] = []
        if neg_themes:
            enriched.append(EnrichedRecommendation(
                text=f"Resolve top complaint '{neg_themes[0]['theme']}' via product update or messaging fix.",
                priority="high",
                rationale=f"'{neg_themes[0]['theme']}' is the highest-frequency negative theme — "
                          "directly impacts conversion and repeat purchase.",
            ))
        if position == "premium" and competitors:
            cheapest = min(competitors, key=lambda c: c["price"])
            enriched.append(EnrichedRecommendation(
                text=f"Reinforce value vs. {cheapest['name']} through bundled offers or warranty extension.",
                priority="high",
                rationale=f"Price gap vs. cheapest competitor (${cheapest['price']:.2f}) is the primary "
                          "switching incentive — reducing it perceptually protects margin.",
            ))
        if direction == "rising":
            enriched.append(EnrichedRecommendation(
                text="Increase paid search budget during rising demand phase.",
                priority="medium",
                rationale=f"Momentum score of {momentum:.2f} indicates above-average demand growth — "
                          "incremental spend now yields above-average return.",
            ))
        if direction == "declining":
            enriched.append(EnrichedRecommendation(
                text="Introduce time-limited promotional pricing to defend volume.",
                priority="high",
                rationale=f"Declining trend with momentum {momentum:.2f} signals shrinking organic demand — "
                          "price promotion is the fastest lever to maintain sell-through.",
            ))
        enriched.append(EnrichedRecommendation(
            text="Audit and optimise product listings across all top platforms.",
            priority="low",
            rationale="Platform listing quality directly affects organic ranking and conversion rate "
                      "independent of market conditions.",
        ))

        return DeepAnalysisSection(
            key_risks=risks[:3],
            market_opportunities=opportunities[:3],
            enriched_recommendations=enriched[:5],
        )
