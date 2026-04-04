import asyncio
import random
from datetime import date
from typing import TYPE_CHECKING, Any

from app.models.tool_outputs import MonthlyPoint, TrendData, ToolResult
from app.tools.base import BaseTool

if TYPE_CHECKING:
    from app.orchestrator.context import AnalysisContext

# ── Category trend profiles ───────────────────────────────────────────────────
TREND_PROFILES: dict[str, dict[str, Any]] = {
    "consumer electronics": {
        "base_direction": "stable",
        "momentum_range": (0.55, 0.85),
        # Month multipliers (1=Jan … 12=Dec); electronics spike Nov/Dec for holidays
        "seasonal_multipliers": [0.85, 0.80, 0.90, 0.95, 0.95, 0.90, 0.92, 0.93, 1.00, 1.05, 1.35, 1.45],
        "seasonal_pattern": "Strong Q4 peak driven by holiday gifting season (Nov/Dec +35-45%)",
        "base_search_volume": 80_000,
        "base_price": 900.0,
        "forecast_template": (
            "Stable demand with seasonal peaks in Q4. "
            "Competitive pressure from Android flagships is steady. "
            "Price elasticity remains low in premium segment — "
            "market is unlikely to soften significantly in the next 6 months."
        ),
    },
    "athletic footwear": {
        "base_direction": "rising",
        "momentum_range": (0.60, 0.82),
        # Spikes in Jan (New Year fitness) and May-Jun (summer prep)
        "seasonal_multipliers": [1.25, 1.10, 1.05, 1.00, 1.15, 1.20, 0.95, 0.90, 1.00, 1.05, 1.10, 1.00],
        "seasonal_pattern": "January fitness spike (+25%) and pre-summer uplift (May/Jun +15-20%)",
        "base_search_volume": 55_000,
        "base_price": 140.0,
        "forecast_template": (
            "Athleisure trend continues to drive above-category growth. "
            "Collaborations and limited-edition releases create demand spikes. "
            "Direct-to-consumer channels gaining share vs. multi-brand retailers. "
            "Expect 8-12% YoY growth continuation for premium athletic brands."
        ),
    },
    "home appliances": {
        "base_direction": "stable",
        "momentum_range": (0.40, 0.65),
        "seasonal_multipliers": [0.90, 0.85, 1.05, 1.10, 1.15, 1.05, 0.95, 0.95, 1.00, 1.05, 1.20, 1.10],
        "seasonal_pattern": "Spring cleaning season uplift (Mar-May +10-15%) and pre-holiday (Nov +20%)",
        "base_search_volume": 25_000,
        "base_price": 450.0,
        "forecast_template": (
            "Stable replacement cycle demand. Smart-home integration driving upgrade interest. "
            "Energy efficiency regulations in EU and US accelerating early replacement. "
            "Supply chain normalised post-2022. Steady pricing expected."
        ),
    },
    "fashion": {
        "base_direction": "rising",
        "momentum_range": (0.50, 0.78),
        "seasonal_multipliers": [0.90, 0.85, 1.15, 1.20, 1.10, 0.95, 0.90, 0.95, 1.10, 1.05, 1.25, 1.20],
        "seasonal_pattern": "Spring/Summer launch peaks (Mar-Apr) and pre-holiday surge (Nov-Dec)",
        "base_search_volume": 40_000,
        "base_price": 90.0,
        "forecast_template": (
            "Social commerce and influencer marketing driving steady demand growth. "
            "Fast-fashion pressure intensifying from Asian platforms. "
            "Sustainability narrative becoming a key differentiator for premium positioning. "
            "Mobile-first shopping experience critical for conversion."
        ),
    },
    "_default": {
        "base_direction": "stable",
        "momentum_range": (0.40, 0.65),
        "seasonal_multipliers": [1.0] * 12,
        "seasonal_pattern": None,
        "base_search_volume": 20_000,
        "base_price": 200.0,
        "forecast_template": (
            "Market shows consistent demand across the year. "
            "No significant seasonal distortion detected. "
            "Competitive landscape stable with incremental pricing pressure."
        ),
    },
}


def _determine_direction(profile: dict, seed: int) -> str:
    base = profile["base_direction"]
    # Small chance the direction differs from category baseline (adds realism)
    if (seed % 7) == 0:
        return "rising" if base == "stable" else "stable"
    return base


class TrendAnalyzerTool(BaseTool):
    """
    Simulates market trend analysis using search volume and price history data.

    Mock strategy:
    - 12-month synthetic time series built from category base values +
      seasonal multipliers + deterministic noise seeded by product name.
    - Same product always produces the same trend data (reproducible).
    - Direction determination has a small category-override probability to
      add realism (not every product follows the exact category trend).

    In production this would query Google Trends API, SimilarWeb, price
    tracking services (CamelCamelCamel, Keepa) or a data warehouse.
    """

    name = "trend_analyzer"
    description = "Analyses 12-month search volume and pricing trends to assess market momentum and seasonality"

    async def execute(self, context: "AnalysisContext") -> ToolResult:
        await asyncio.sleep(0.12)  # simulate data fetch + computation

        profile = TREND_PROFILES.get(
            context.request.category.lower(),
            TREND_PROFILES["_default"],
        )
        seed = abs(hash(context.request.product_name.lower())) % 10_000
        rng = random.Random(seed)

        momentum_lo, momentum_hi = profile["momentum_range"]
        momentum = round(momentum_lo + rng.random() * (momentum_hi - momentum_lo), 3)

        direction = _determine_direction(profile, seed)

        search_series = self._generate_series(
            base=profile["base_search_volume"],
            multipliers=profile["seasonal_multipliers"],
            direction=direction,
            rng=rng,
            is_price=False,
        )
        price_series = self._generate_series(
            base=profile["base_price"],
            multipliers=[1.0] * 12,  # price doesn't follow seasonal pattern as strongly
            direction=direction,
            rng=rng,
            is_price=True,
        )

        trend_data = TrendData(
            trend_direction=direction,
            momentum_score=momentum,
            seasonal_pattern=profile["seasonal_pattern"],
            search_volume_trend=search_series,
            price_trend=price_series,
            forecast_summary=profile["forecast_template"],
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data=trend_data.model_dump(),
        )

    def _generate_series(
        self,
        base: float,
        multipliers: list[float],
        direction: str,
        rng: random.Random,
        is_price: bool,
    ) -> list[MonthlyPoint]:
        today = date.today()
        # Start 11 months ago
        start_month = (today.month - 11) % 12 or 12
        start_year = today.year - (1 if today.month <= 11 else 0)

        trend_slope = {"rising": 1.008, "stable": 1.001, "declining": 0.993}[direction]
        if is_price:
            trend_slope = 1.0 + (trend_slope - 1.0) * 0.3  # prices change slower

        points: list[MonthlyPoint] = []
        value = base
        for i in range(12):
            month_idx = (start_month - 1 + i) % 12
            year = start_year + ((start_month - 1 + i) // 12)
            label = f"{year}-{month_idx + 1:02d}"

            seasonal = multipliers[month_idx]
            noise = 0.95 + rng.random() * 0.10  # ±5% noise
            value = value * trend_slope * seasonal * noise

            # Keep price series smoother
            display_value = round(value / seasonal, 2) if is_price else round(value, 0)
            points.append(MonthlyPoint(month=label, value=display_value))

        return points
