from dataclasses import dataclass, field

from app.tools.base import BaseTool
from app.tools.product_collector import ProductCollectorTool
from app.tools.sentiment_analyzer import SentimentAnalyzerTool
from app.tools.trend_analyzer import TrendAnalyzerTool


@dataclass
class PipelineStep:
    """
    A single step in the analysis pipeline.

    required=True -> if this tool fails, the whole pipeline aborts.
    required=False -> In failure, a warning is recorded, but the pipeline continues. The final report notes the gap.
    """

    tool: BaseTool
    required: bool = True
    depends_on: list[str] = field(default_factory=list)


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
        # The "deep" flag changes how the agent synthesises results (more LLM calls),
        # not which tools run.
        return [
            PipelineStep(tool=self._product_collector, required=True),
            PipelineStep(tool=self._sentiment_analyzer, required=False),
            PipelineStep(tool=self._trend_analyzer, required=True),
        ]
