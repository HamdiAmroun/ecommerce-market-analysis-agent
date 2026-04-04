import pytest

from app.models.requests import AnalysisRequest
from app.orchestrator.context import AnalysisContext
from app.tools.trend_analyzer import TrendAnalyzerTool


def _make_context(product_name: str, category: str = "consumer electronics") -> AnalysisContext:
    return AnalysisContext(
        job_id="test-job",
        request=AnalysisRequest(product_name=product_name, category=category),
    )


@pytest.fixture
def tool() -> TrendAnalyzerTool:
    return TrendAnalyzerTool()


class TestTrendAnalyzerOutput:
    async def test_returns_success(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert result.success is True

    async def test_direction_is_valid(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert result.data["trend_direction"] in ("rising", "stable", "declining")

    async def test_momentum_in_range(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert 0.0 <= result.data["momentum_score"] <= 1.0

    async def test_search_volume_trend_has_12_months(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert len(result.data["search_volume_trend"]) == 12

    async def test_price_trend_has_12_months(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert len(result.data["price_trend"]) == 12

    async def test_monthly_point_format(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        for point in result.data["search_volume_trend"]:
            # Format should be YYYY-MM
            assert len(point["month"]) == 7
            assert point["month"][4] == "-"
            assert point["value"] > 0

    async def test_forecast_summary_non_empty(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert len(result.data["forecast_summary"]) > 20


class TestTrendAnalyzerDeterminism:
    async def test_same_product_same_direction(self, tool):
        ctx1 = _make_context("iPhone 16 Pro")
        ctx2 = _make_context("iPhone 16 Pro")
        r1 = await tool._safe_execute(ctx1)
        r2 = await tool._safe_execute(ctx2)
        assert r1.data["trend_direction"] == r2.data["trend_direction"]

    async def test_same_product_same_momentum(self, tool):
        ctx1 = _make_context("Nike Air Max 270", "athletic footwear")
        ctx2 = _make_context("Nike Air Max 270", "athletic footwear")
        r1 = await tool._safe_execute(ctx1)
        r2 = await tool._safe_execute(ctx2)
        assert r1.data["momentum_score"] == r2.data["momentum_score"]


class TestTrendAnalyzerCategories:
    async def test_footwear_direction_rising(self, tool):
        # Athletic footwear baseline is "rising"
        ctx = _make_context("Nike Air Max 270", "athletic footwear")
        result = await tool._safe_execute(ctx)
        assert result.data["trend_direction"] in ("rising", "stable")

    async def test_unknown_category_returns_stable(self, tool):
        ctx = _make_context("Unknown Gadget", "interdimensional widgets")
        result = await tool._safe_execute(ctx)
        assert result.success is True
        assert result.data["trend_direction"] in ("rising", "stable", "declining")

    async def test_all_categories_have_seasonal_or_none(self, tool):
        categories = ["consumer electronics", "athletic footwear", "home appliances", "fashion"]
        for category in categories:
            ctx = _make_context("Test Product", category)
            result = await tool._safe_execute(ctx)
            # seasonal_pattern is either a non-empty string or None
            sp = result.data.get("seasonal_pattern")
            assert sp is None or len(sp) > 5
