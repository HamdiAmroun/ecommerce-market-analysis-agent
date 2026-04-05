import asyncio
import hashlib
import random
from typing import TYPE_CHECKING, Any

from app.models.tool_outputs import ReviewSample, SentimentData, SentimentTheme, ToolResult
from app.tools.base import BaseTool

if TYPE_CHECKING:
    from app.orchestrator.context import AnalysisContext

# ── Sentiment profiles per product category ───────────────────────────────────
# Each profile defines the realistic sentiment distribution for that category.

SENTIMENT_PROFILES: dict[str, dict[str, Any]] = {
    "consumer electronics": {
        "score_range": (0.35, 0.72),
        "positive_themes": [
            ("performance", 1450), ("camera quality", 1320), ("build quality", 980),
            ("ecosystem integration", 870), ("display quality", 760), ("software updates", 640),
        ],
        "negative_themes": [
            ("battery life", 890), ("price", 740), ("charger not included", 620),
            ("heating issues", 380), ("storage pricing", 310),
        ],
        "review_count_range": (1_200, 45_000),
        "sample_positive": [
            "Absolutely blown away by the camera system. Night mode photos look professional.",
            "Best phone I've ever owned. The performance is buttery smooth even with heavy apps.",
            "Premium build quality — feels solid and well-crafted in hand.",
            "Battery improved significantly over the previous model. Lasts me a full day easily.",
            "The display is stunning. Colors are vivid and accurate for photo editing.",
        ],
        "sample_negative": [
            "Great phone but the battery drains faster than expected during video recording.",
            "Why is the fast charger not included in the box at this price point?",
            "Runs warm during gaming sessions. Not a dealbreaker but noticeable.",
            "iCloud storage upselling gets tiresome. Base 128GB fills up fast.",
            "Expensive for what it offers compared to Android alternatives at half the price.",
        ],
    },
    "athletic footwear": {
        "score_range": (0.55, 0.88),
        "positive_themes": [
            ("comfort", 2100), ("style", 1780), ("durability", 1340),
            ("cushioning", 1120), ("fit", 990), ("versatility", 720),
        ],
        "negative_themes": [
            ("runs small", 680), ("price", 520), ("sole durability", 410),
            ("narrow fit", 360), ("color fading", 280),
        ],
        "review_count_range": (800, 22_000),
        "sample_positive": [
            "Most comfortable running shoes I've owned. Wore them all day at a theme park, zero blisters.",
            "The air cushioning is incredible. My knees thank me after long runs.",
            "Stylish enough to wear casually but supportive enough for gym work.",
            "True to size and width. Fits perfectly right out of the box.",
            "Six months in and they still look and feel new. Very impressed with durability.",
        ],
        "sample_negative": [
            "Size up by half — they run a bit small, especially in the toe box.",
            "Premium price tag but the sole shows wear faster than expected for trail running.",
            "The white colorway is stunning but stains easily and hard to clean.",
            "A bit narrow for wide feet. Comfortable once broken in but initial fit was tight.",
            "For the price, I expected a more premium upper material.",
        ],
    },
    "home appliances": {
        "score_range": (0.40, 0.78),
        "positive_themes": [
            ("ease of use", 890), ("energy efficiency", 760), ("quiet operation", 640),
            ("smart features", 580), ("cleaning performance", 520),
        ],
        "negative_themes": [
            ("setup complexity", 420), ("customer support", 380), ("price", 310),
            ("build quality", 270), ("app connectivity issues", 240),
        ],
        "review_count_range": (300, 8_000),
        "sample_positive": [
            "Easy to set up and works perfectly. Energy Star rating is genuine.",
            "Noticeably quieter than our old unit. A night and day difference.",
            "Smart app controls work flawlessly. Love scheduling cycles remotely.",
            "Cleans thoroughly on a single cycle. Very impressed.",
            "Energy savings showed up on our electricity bill within the first month.",
        ],
        "sample_negative": [
            "Great appliance but the setup manual is confusing. Took two hours to configure.",
            "Customer support was slow to respond when I had a question about the WiFi module.",
            "Expensive for the feature set. Comparable models from other brands cost less.",
            "The plastic door handle feels flimsy relative to the price.",
            "App drops connection occasionally. A firmware update would fix this.",
        ],
    },
    "fashion": {
        "score_range": (0.45, 0.82),
        "positive_themes": [
            ("style", 1650), ("quality materials", 980), ("fit", 870),
            ("value for money", 720), ("packaging", 480),
        ],
        "negative_themes": [
            ("sizing inconsistency", 580), ("color not as shown", 420),
            ("stitching quality", 360), ("shrinkage", 310), ("delivery time", 220),
        ],
        "review_count_range": (500, 15_000),
        "sample_positive": [
            "Perfect fit and the fabric feels luxurious. Already ordered two more colors.",
            "Great quality for the price. Looks way more expensive than it is.",
            "Fast shipping and beautiful packaging. Makes a great gift.",
            "Exactly as pictured. The color is vibrant and the material is premium.",
            "Washed five times and still looks brand new. Excellent durability.",
        ],
        "sample_negative": [
            "Sizing runs large — order a size down from your usual.",
            "The color looks slightly different from the product photos. Still nice though.",
            "The stitching on one seam came loose after the second wash.",
            "Lovely design but shrank one size after tumble drying despite following instructions.",
            "Delivery took longer than estimated. Product itself is good quality.",
        ],
    },
    "_default": {
        "score_range": (0.40, 0.70),
        "positive_themes": [
            ("quality", 800), ("value", 650), ("design", 530),
            ("functionality", 480), ("packaging", 320),
        ],
        "negative_themes": [
            ("price", 400), ("durability", 320), ("customer support", 280),
            ("missing features", 220), ("documentation", 180),
        ],
        "review_count_range": (200, 5_000),
        "sample_positive": [
            "Excellent quality and exactly as described. Very satisfied.",
            "Great value for money. Works perfectly for my use case.",
            "Well-designed product. Easy to use and looks great.",
            "Arrived quickly and well-packaged. No complaints.",
            "Does exactly what it promises. Would recommend to a friend.",
        ],
        "sample_negative": [
            "A bit pricey but the quality justifies it for the right buyer.",
            "Durability is questionable for heavy daily use.",
            "Customer support was slow to respond to my inquiry.",
            "Missing a few features I expected at this price point.",
            "The manual is poorly written. Took time to figure out the setup.",
        ],
    },
}


def _score_to_label(score: float) -> str:
    if score >= 0.6:
        return "positive"
    if score >= 0.2:
        return "mixed"
    if score >= -0.1:
        return "neutral"
    return "negative"


class SentimentAnalyzerTool(BaseTool):
    """
    Simulates customer review sentiment analysis across review platforms.

    Mock strategy:
    - Category profiles define realistic score ranges, theme distributions, and sample review pools.
    - A seed derived from hash(product_name) makes output deterministic:
      the same product always produces the same sentiment data (reproducible demos, reliable tests).
    - Themes and review counts are drawn from the pool with minor variance to feel realistic rather than perfectly round.

    In production this will call a review aggregation service (e.g., Trustpilot, Amazon reviews API) and
    run actual NLP (Transformers, VADER, or an LLM).
    """

    name = "sentiment_analyzer"
    description = "Analyses customer reviews to extract overall sentiment scores and recurring themes"

    async def execute(self, context: "AnalysisContext") -> ToolResult:
        await asyncio.sleep(0.08)  # simulate processing time

        profile = SENTIMENT_PROFILES.get(
            context.request.category.lower(),
            SENTIMENT_PROFILES["_default"],
        )
        rng = random.Random(int(hashlib.md5(context.request.product_name.lower().encode()).hexdigest(), 16) % 10_000)

        # ── Cross-tool influence: read ProductCollector output from blackboard ─
        # Market position affects review expectations and sentiment distribution.
        # Premium products attract more critical reviewers (higher expectations),
        # budget products get more lenient scores (value expectations more easily met).
        product_data = context.get_tool_data("product_collector")
        market_position = product_data.get("market_position", "mid-range") if product_data else "mid-range"

        lo, hi = profile["score_range"]
        if market_position == "premium":
            # Tighten range downward: higher price → higher expectations → more scrutiny
            lo = round(max(lo - 0.05, -1.0), 3)
            hi = round(max(hi - 0.04, lo + 0.10), 3)
        elif market_position == "budget":
            # Ease range upward: value expectations are easier to meet
            lo = round(min(lo + 0.05, 1.0), 3)
            hi = round(min(hi + 0.05, 1.0), 3)

        overall_score = round(lo + rng.random() * (hi - lo), 3)
        label = _score_to_label(overall_score)

        rc_lo, rc_hi = profile["review_count_range"]
        review_count = rng.randint(rc_lo, rc_hi)

        # Pick themes with slight count variance.
        # For premium products boost price-related negative theme frequency —
        # high-price items attract disproportionate value-for-money criticism.
        price_boost = 1.35 if market_position == "premium" else 1.0

        pos_themes = [
            SentimentTheme(
                theme=t,
                sentiment="positive",
                frequency=int(freq * (0.85 + rng.random() * 0.3)),
            )
            for t, freq in profile["positive_themes"]
        ]
        neg_themes = [
            SentimentTheme(
                theme=t,
                sentiment="negative",
                frequency=int(
                    freq
                    * (0.85 + rng.random() * 0.3)
                    * (price_boost if "price" in t.lower() else 1.0)
                ),
            )
            for t, freq in profile["negative_themes"]
        ]

        sample_pos_text = rng.choice(profile["sample_positive"])
        sample_neg_text = rng.choice(profile["sample_negative"])

        sentiment_data = SentimentData(
            overall_score=overall_score,
            label=label,
            review_count=review_count,
            themes=pos_themes + neg_themes,
            sample_reviews=[
                ReviewSample(
                    text=sample_pos_text,
                    rating=round(4.0 + rng.random() * 1.0, 1),
                    sentiment="positive",
                ),
                ReviewSample(
                    text=sample_neg_text,
                    rating=round(1.5 + rng.random() * 1.5, 1),
                    sentiment="negative",
                ),
            ],
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            data=sentiment_data.model_dump(),
        )
