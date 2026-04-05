import pytest

from app.models.requests import AnalysisRequest
from app.orchestrator.context import AnalysisContext
from app.tools.product_collector import ProductCollectorTool


def _make_context(product_name: str, category: str = "consumer electronics") -> AnalysisContext:
    return AnalysisContext(
        job_id="test-job",
        request=AnalysisRequest(
            product_name=product_name,
            category=category,
        ),
    )


@pytest.fixture
def tool() -> ProductCollectorTool:
    return ProductCollectorTool()


class TestProductCollectorKnownProduct:
    async def test_known_product_returns_success(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert result.success is True
        assert result.error is None

    async def test_known_product_has_platforms(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert len(result.data["platforms"]) >= 3

    async def test_known_product_has_competitors(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert len(result.data["competitors"]) >= 2

    async def test_known_product_price_range_valid(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert result.data["price_range_min"] <= result.data["average_price"]
        assert result.data["average_price"] <= result.data["price_range_max"]

    async def test_known_product_market_position_valid(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert result.data["market_position"] in ("budget", "mid-range", "premium")

    async def test_known_product_premium_position(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert result.data["market_position"] == "premium"


class TestProductCollectorUnknownProduct:
    async def test_unknown_product_returns_success(self, tool):
        ctx = _make_context("XyloGadget Pro 3000", "consumer electronics")
        result = await tool._safe_execute(ctx)
        assert result.success is True

    async def test_unknown_product_has_platforms(self, tool):
        ctx = _make_context("XyloGadget Pro 3000", "consumer electronics")
        result = await tool._safe_execute(ctx)
        assert len(result.data["platforms"]) >= 1

    async def test_unknown_product_deterministic(self, tool):
        ctx1 = _make_context("Mystery Widget X", "consumer electronics")
        ctx2 = _make_context("Mystery Widget X", "consumer electronics")
        r1 = await tool._safe_execute(ctx1)
        r2 = await tool._safe_execute(ctx2)
        assert r1.data["average_price"] == r2.data["average_price"]

    async def test_unknown_product_different_names_differ(self, tool):
        ctx_a = _make_context("Alpha Widget", "consumer electronics")
        ctx_b = _make_context("Beta Widget", "consumer electronics")
        r_a = await tool._safe_execute(ctx_a)
        r_b = await tool._safe_execute(ctx_b)
        # Different products should produce different prices
        assert r_a.data["average_price"] != r_b.data["average_price"]

    async def test_all_prices_positive(self, tool):
        ctx = _make_context("Unknown Item", "home appliances")
        result = await tool._safe_execute(ctx)
        for platform in result.data["platforms"]:
            assert platform["price"] > 0

    async def test_footwear_category(self, tool):
        ctx = _make_context("Nike Air Max 270", "athletic footwear")
        result = await tool._safe_execute(ctx)
        assert result.success is True
        assert result.data["category"] == "athletic footwear"


class TestProductCollectorDataSource:
    async def test_known_product_has_catalog_source(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert result.data["data_source"] == "catalog"

    async def test_unknown_product_has_generic_source(self, tool):
        ctx = _make_context("XyloGadget Pro 3000")
        result = await tool._safe_execute(ctx)
        assert result.data["data_source"] == "generic"

    async def test_stable_hash_across_calls(self, tool):
        """md5-based seed must produce identical output on every call."""
        ctx1 = _make_context("Mystery Widget X")
        ctx2 = _make_context("Mystery Widget X")
        r1 = await tool._safe_execute(ctx1)
        r2 = await tool._safe_execute(ctx2)
        assert r1.data["average_price"] == r2.data["average_price"]
        assert r1.data["data_source"] == r2.data["data_source"]
