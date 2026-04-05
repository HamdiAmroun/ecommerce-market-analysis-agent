from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standardized output returned by every tool execution."""

    tool_name: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    skipped: bool = False  # True when a skip_if condition prevented execution
    execution_time_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Product collector outputs ─────────────────────────────────────────────────
class PlatformListing(BaseModel):
    name: str
    price: float
    currency: str = "USD"
    rating: float | None = None
    url: str = ""


class CompetitorInfo(BaseModel):
    name: str
    price: float
    market_share_pct: float | None = None


class ProductData(BaseModel):
    product_name: str
    category: str
    platforms: list[PlatformListing]
    competitors: list[CompetitorInfo]
    average_price: float
    price_range_min: float
    price_range_max: float
    market_position: Literal["budget", "mid-range", "premium"]
    data_source: Literal["catalog", "generic"] = "catalog"  # drives dynamic skip decisions downstream


# ── Sentiment analyzer outputs ────────────────────────────────────────────────
class SentimentTheme(BaseModel):
    theme: str
    sentiment: Literal["positive", "negative"]
    frequency: int


class ReviewSample(BaseModel):
    text: str
    rating: float
    sentiment: Literal["positive", "negative", "neutral"]


class SentimentData(BaseModel):
    overall_score: float = Field(ge=-1.0, le=1.0)
    label: Literal["positive", "neutral", "negative", "mixed"]
    review_count: int
    themes: list[SentimentTheme]
    sample_reviews: list[ReviewSample]


# ── Trend analyzer outputs ────────────────────────────────────────────────────
class MonthlyPoint(BaseModel):
    month: str  # "YYYY-MM"
    value: float


class TrendData(BaseModel):
    trend_direction: Literal["rising", "stable", "declining"]
    momentum_score: float = Field(ge=0.0, le=1.0)
    seasonal_pattern: str | None = None
    search_volume_trend: list[MonthlyPoint]
    price_trend: list[MonthlyPoint]
    forecast_summary: str
