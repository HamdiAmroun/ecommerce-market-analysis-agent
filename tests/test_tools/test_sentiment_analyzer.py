import pytest

from app.models.requests import AnalysisRequest
from app.orchestrator.context import AnalysisContext
from app.tools.sentiment_analyzer import SentimentAnalyzerTool


def _make_context(product_name: str, category: str = "consumer electronics") -> AnalysisContext:
    return AnalysisContext(
        job_id="test-job",
        request=AnalysisRequest(product_name=product_name, category=category),
    )


@pytest.fixture
def tool() -> SentimentAnalyzerTool:
    return SentimentAnalyzerTool()


class TestSentimentAnalyzerOutput:
    async def test_returns_success(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert result.success is True

    async def test_score_in_range(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert -1.0 <= result.data["overall_score"] <= 1.0

    async def test_label_is_valid(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert result.data["label"] in ("positive", "neutral", "negative", "mixed")

    async def test_review_count_positive(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert result.data["review_count"] > 0

    async def test_themes_non_empty(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert len(result.data["themes"]) > 0

    async def test_theme_sentiments_valid(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        for theme in result.data["themes"]:
            assert theme["sentiment"] in ("positive", "negative")

    async def test_sample_reviews_non_empty(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        assert len(result.data["sample_reviews"]) > 0

    async def test_sample_reviews_have_text(self, tool):
        ctx = _make_context("iPhone 16 Pro")
        result = await tool._safe_execute(ctx)
        for review in result.data["sample_reviews"]:
            assert len(review["text"]) > 10


class TestSentimentAnalyzerDeterminism:
    async def test_same_product_same_score(self, tool):
        ctx1 = _make_context("iPhone 16 Pro")
        ctx2 = _make_context("iPhone 16 Pro")
        r1 = await tool._safe_execute(ctx1)
        r2 = await tool._safe_execute(ctx2)
        assert r1.data["overall_score"] == r2.data["overall_score"]

    async def test_same_product_same_review_count(self, tool):
        ctx1 = _make_context("Nike Air Max 270", "athletic footwear")
        ctx2 = _make_context("Nike Air Max 270", "athletic footwear")
        r1 = await tool._safe_execute(ctx1)
        r2 = await tool._safe_execute(ctx2)
        assert r1.data["review_count"] == r2.data["review_count"]

    async def test_different_products_differ(self, tool):
        ctx_a = _make_context("iPhone 16 Pro")
        ctx_b = _make_context("Samsung Galaxy S25", "consumer electronics")
        r_a = await tool._safe_execute(ctx_a)
        r_b = await tool._safe_execute(ctx_b)
        assert r_a.data["overall_score"] != r_b.data["overall_score"]


class TestSentimentAnalyzerCategories:
    async def test_electronics_category(self, tool):
        ctx = _make_context("Laptop X", "consumer electronics")
        result = await tool._safe_execute(ctx)
        assert result.success is True

    async def test_footwear_category(self, tool):
        ctx = _make_context("Running Shoe Y", "athletic footwear")
        result = await tool._safe_execute(ctx)
        assert result.success is True

    async def test_unknown_category_uses_default(self, tool):
        ctx = _make_context("Mystery Item", "underwater basketweaving supplies")
        result = await tool._safe_execute(ctx)
        assert result.success is True
        assert -1.0 <= result.data["overall_score"] <= 1.0
