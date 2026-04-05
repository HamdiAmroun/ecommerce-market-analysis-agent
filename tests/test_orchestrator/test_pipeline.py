import pytest

from app.orchestrator.pipeline import AnalysisPipeline


@pytest.fixture
def pipeline() -> AnalysisPipeline:
    return AnalysisPipeline()


class TestPipelineSteps:
    def test_quick_returns_two_steps(self, pipeline):
        steps = pipeline.get_steps("quick")
        assert len(steps) == 2

    def test_standard_returns_three_steps(self, pipeline):
        steps = pipeline.get_steps("standard")
        assert len(steps) == 3

    def test_deep_returns_three_steps(self, pipeline):
        steps = pipeline.get_steps("deep")
        assert len(steps) == 3

    def test_quick_no_sentiment(self, pipeline):
        steps = pipeline.get_steps("quick")
        tool_names = [s.tool.name for s in steps]
        assert "sentiment_analyzer" not in tool_names

    def test_standard_includes_sentiment(self, pipeline):
        steps = pipeline.get_steps("standard")
        tool_names = [s.tool.name for s in steps]
        assert "sentiment_analyzer" in tool_names

    def test_product_collector_always_required(self, pipeline):
        for depth in ("quick", "standard", "deep"):
            steps = pipeline.get_steps(depth)
            product_step = next(s for s in steps if s.tool.name == "product_collector")
            assert product_step.required is True

    def test_trend_analyzer_always_required(self, pipeline):
        for depth in ("quick", "standard", "deep"):
            steps = pipeline.get_steps(depth)
            trend_step = next(s for s in steps if s.tool.name == "trend_analyzer")
            assert trend_step.required is True

    def test_sentiment_is_optional_in_standard(self, pipeline):
        steps = pipeline.get_steps("standard")
        sentiment_step = next(s for s in steps if s.tool.name == "sentiment_analyzer")
        assert sentiment_step.required is False

    def test_quick_first_step_is_product_collector(self, pipeline):
        steps = pipeline.get_steps("quick")
        assert steps[0].tool.name == "product_collector"

    def test_standard_first_step_is_product_collector(self, pipeline):
        steps = pipeline.get_steps("standard")
        assert steps[0].tool.name == "product_collector"


class TestPipelineSkipCondition:
    def test_sentiment_step_has_skip_if(self, pipeline):
        """SentimentAnalyzer step must carry a skip_if callable."""
        steps = pipeline.get_steps("standard")
        sentiment_step = next(s for s in steps if s.tool.name == "sentiment_analyzer")
        assert callable(sentiment_step.skip_if)

    def test_required_steps_have_no_skip_if(self, pipeline):
        """Required tools should never be skippable."""
        steps = pipeline.get_steps("standard")
        for step in steps:
            if step.required:
                assert step.skip_if is None

    def test_skip_if_true_for_generic_product(self, pipeline):
        """skip_if must return True when product data_source is 'generic'."""
        from app.models.requests import AnalysisRequest
        from app.models.tool_outputs import ToolResult
        from app.orchestrator.context import AnalysisContext

        ctx = AnalysisContext(
            job_id="skip-test",
            request=AnalysisRequest(product_name="Unknown Widget", category="consumer electronics"),
        )
        ctx.add_tool_result(ToolResult(
            tool_name="product_collector",
            success=True,
            data={"data_source": "generic", "market_position": "mid-range", "average_price": 200.0},
        ))
        steps = pipeline.get_steps("standard")
        sentiment_step = next(s for s in steps if s.tool.name == "sentiment_analyzer")
        assert sentiment_step.skip_if(ctx) is True

    def test_skip_if_false_for_catalog_product(self, pipeline):
        """skip_if must return False when product data_source is 'catalog'."""
        from app.models.requests import AnalysisRequest
        from app.models.tool_outputs import ToolResult
        from app.orchestrator.context import AnalysisContext

        ctx = AnalysisContext(
            job_id="skip-test-2",
            request=AnalysisRequest(product_name="iPhone 16 Pro", category="consumer electronics"),
        )
        ctx.add_tool_result(ToolResult(
            tool_name="product_collector",
            success=True,
            data={"data_source": "catalog", "market_position": "premium", "average_price": 999.0},
        ))
        steps = pipeline.get_steps("standard")
        sentiment_step = next(s for s in steps if s.tool.name == "sentiment_analyzer")
        assert sentiment_step.skip_if(ctx) is False
