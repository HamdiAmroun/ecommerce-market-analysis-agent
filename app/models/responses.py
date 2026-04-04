from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Sub-sections of MarketReport ──────────────────────────────────────────────
class PlatformPrice(BaseModel):
    platform: str
    price: float
    currency: str = "USD"


class CompetitorSummary(BaseModel):
    name: str
    price: float
    market_share_pct: float | None = None


class ProductAnalysisSection(BaseModel):
    average_price: float
    price_range_min: float
    price_range_max: float
    market_position: Literal["budget", "mid-range", "premium"]
    competitor_count: int
    top_platforms: list[PlatformPrice]
    top_competitors: list[CompetitorSummary]


class SentimentThemeSummary(BaseModel):
    theme: str
    sentiment: Literal["positive", "negative"]
    frequency: int


class SentimentSection(BaseModel):
    overall_score: float = Field(ge=-1.0, le=1.0, description="-1 = very negative, +1 = very positive")
    label: Literal["positive", "neutral", "negative", "mixed"]
    review_count: int
    top_themes: list[SentimentThemeSummary]
    sample_positive: str | None = None
    sample_negative: str | None = None


class MonthlyDataPoint(BaseModel):
    month: str  # "YYYY-MM"
    value: float


class TrendSection(BaseModel):
    trend_direction: Literal["rising", "stable", "declining"]
    momentum_score: float = Field(ge=0.0, le=1.0)
    seasonal_pattern: str | None = None
    search_volume_trend: list[MonthlyDataPoint]
    price_trend: list[MonthlyDataPoint]
    forecast_summary: str


class ReportMetadata(BaseModel):
    tool_execution_ms: dict[str, float]
    total_execution_ms: float
    tools_succeeded: int
    tools_failed: int
    warnings: list[str]


# ── Top-level report ──────────────────────────────────────────────────────────
class MarketReport(BaseModel):
    executive_summary: str
    product_analysis: ProductAnalysisSection
    sentiment_analysis: SentimentSection | None = Field(
        default=None,
        description="Absent when analysis_depth='quick' or sentiment tool failed",
    )
    market_trends: TrendSection
    recommendations: list[str] = Field(min_length=1, max_length=7)
    confidence_score: float = Field(ge=0.0, le=1.0)
    generated_by: Literal["llm", "fallback"]
    metadata: ReportMetadata


# ── Job-level response ────────────────────────────────────────────────────────
class AnalysisResponse(BaseModel):
    job_id: str
    status: JobStatus
    product_name: str
    category: str
    target_market: str
    analysis_depth: str
    created_at: datetime
    completed_at: datetime | None = None
    report: MarketReport | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    llm_available: bool
    llm_model: str | None = None
