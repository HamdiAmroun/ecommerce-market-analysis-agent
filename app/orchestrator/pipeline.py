from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from app.tools.base import BaseTool
from app.tools.product_collector import ProductCollectorTool
from app.tools.sentiment_analyzer import SentimentAnalyzerTool
from app.tools.trend_analyzer import TrendAnalyzerTool

if TYPE_CHECKING:
    from app.orchestrator.context import AnalysisContext


@dataclass
class PipelineStep:
    """
    A single step in the analysis pipeline.

    required=True  -> if this tool fails, the whole pipeline aborts.
    required=False -> failure records a warning but the pipeline continues.
    skip_if        -> optional callable evaluated at runtime against the current
                      AnalysisContext. When it returns True the tool is skipped
                      entirely (not failed) and a skip record is written to the
                      context. This enables data-driven, dynamic orchestration:
                      the pipeline shape is decided by what previous steps found,
                      not just by the static depth parameter.
    """

    tool: BaseTool
    required: bool = True
    depends_on: list[str] = field(default_factory=list)
    skip_if: Callable[["AnalysisContext"], bool] | None = None


def _should_skip_sentiment(context: "AnalysisContext") -> bool:
    """Runtime skip decision for SentimentAnalyzerTool.

    If ProductCollector returned generic (non-catalog) data the product has no
    established review base — running sentiment analysis would produce category-
    average noise rather than product-specific insight.  It is more honest to
    omit the section and note the gap than to present fabricated scores.

    This is the core dynamic-orchestration hook: the pipeline re-evaluates its
    own shape based on what a prior step actually found.
    """
    product_data = context.get_tool_data("product_collector")
    if not product_data:
        return False  # product step not yet run — don't skip
    return product_data.get("data_source") == "generic"


class AnalysisPipeline:
    """
    Defines the execution graph: which tools run, in what order, and whether each one is mandatory.

    Three depth modes:
    1. quick: ProductCollector -> TrendAnalyzer only, for a fast overview without sentiment insights.
    2. standard: ProductCollector -> SentimentAnalyzer (Optional) -> TrendAnalyzer, the default balanced approach.
    3. deep: Same tools as standard, but the agent's synthesis step performs deeper LLM enrichment
       (e.g., more detailed analysis of sentiment data, cross-referencing trends with sentiment, etc.)

    Question is Why the SentimentAnalyzer is optional here?
    The reason is that the Product pricing and trend data can still generate a useful competitive report
    even without sentiment. Therefore, sentiment failure (e.g., no reviews found) should not block the whole analysis;
    it's an additive signal, not foundational data.
    """

    def __init__(self) -> None:
        # Tool instances are shared across all pipeline runs (stateless)
        self._product_collector = ProductCollectorTool()
        self._sentiment_analyzer = SentimentAnalyzerTool()
        self._trend_analyzer = TrendAnalyzerTool()

    @property
    def all_tools(self) -> dict[str, BaseTool]:
        return {
            self._product_collector.name: self._product_collector,
            self._sentiment_analyzer.name: self._sentiment_analyzer,
            self._trend_analyzer.name: self._trend_analyzer,
        }

    def get_steps(self, analysis_depth: str) -> list[PipelineStep]:
        if analysis_depth == "quick":
            return [
                PipelineStep(tool=self._product_collector, required=True),
                PipelineStep(tool=self._trend_analyzer, required=True),
            ]

        # Both "standard" and "deep" use the same 3-tool pipeline.
        # The "deep" flag changes how the agent synthesises results (richer LLM
        # enrichment + structured deep_analysis section), not which tools run.
        # The skip_if on SentimentAnalyzer makes the pipeline dynamic: if
        # ProductCollector found no catalog entry the sentiment step is skipped
        # at runtime rather than running and producing category-average noise.
        return [
            PipelineStep(tool=self._product_collector, required=True),
            PipelineStep(
                tool=self._sentiment_analyzer,
                required=False,
                skip_if=_should_skip_sentiment,
            ),
            PipelineStep(tool=self._trend_analyzer, required=True),
        ]
