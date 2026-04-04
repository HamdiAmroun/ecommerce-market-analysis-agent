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
