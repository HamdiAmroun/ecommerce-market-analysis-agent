from typing import TYPE_CHECKING

from app.llm.schemas import schema_as_string

if TYPE_CHECKING:
    from app.orchestrator.context import AnalysisContext

# Schemas loaded once at import time — avoids repeated disk reads per request.
_SYNTHESIS_SCHEMA = schema_as_string("report_synthesis.json")
_DEEP_SYNTHESIS_SCHEMA = schema_as_string("deep_synthesis.json")


def build_synthesis_prompt(context: "AnalysisContext") -> str:
    """
    Build the user-turn prompt from collected tool data.

    Compression strategy (keeping token count under ~500 for cost efficiency):
    - Product: top 3 platforms with prices, top 3 competitors with share
    - Sentiment: score + label + top 3 positive and 2 negative themes, one sample each
    - Trends: direction, momentum, seasonal note, forecast (truncated to 200 chars)

    The schema is appended at the end, so the model knows exactly what to return.
    """
    lines: list[str] = [
        f"Product: {context.request.product_name}",
        f"Category: {context.request.category}",
        f"Target market: {context.request.target_market}",
        "",
    ]

    # ── Product & competitor data ─────────────────────────────────────────────
    product = context.get_tool_data("product_collector")
    if product:
        lines.append("=== PRODUCT & COMPETITOR DATA ===")
        lines.append(
            f"Avg price: ${product['average_price']:.2f} "
            f"(range ${product['price_range_min']:.2f}–${product['price_range_max']:.2f}, "
            f"{product['market_position']} segment)"
        )
        for p in product.get("platforms", [])[:3]:
            lines.append(f"  {p['name']}: ${p['price']:.2f}")
        lines.append("Competitors:")
        for c in product.get("competitors", [])[:3]:
            share = f" | {c['market_share_pct']}% share" if c.get("market_share_pct") else ""
            lines.append(f"  {c['name']}: ${c['price']:.2f}{share}")
        lines.append("")

    # ── Sentiment data ────────────────────────────────────────────────────────
    sentiment = context.get_tool_data("sentiment_analyzer")
    if sentiment:
        lines.append("=== CUSTOMER SENTIMENT ===")
        lines.append(
            f"Score: {sentiment['overall_score']:.2f} ({sentiment['label']}) "
            f"— {sentiment['review_count']:,} reviews"
        )
        themes = sentiment.get("themes", [])
        pos = [t["theme"] for t in themes if t["sentiment"] == "positive"][:3]
        neg = [t["theme"] for t in themes if t["sentiment"] == "negative"][:2]
        if pos:
            lines.append(f"Positive themes: {', '.join(pos)}")
        if neg:
            lines.append(f"Negative themes: {', '.join(neg)}")
        reviews = sentiment.get("sample_reviews", [])
        pos_r = next((r["text"] for r in reviews if r["sentiment"] == "positive"), None)
        neg_r = next((r["text"] for r in reviews if r["sentiment"] == "negative"), None)
        if pos_r:
            lines.append(f'Sample (+): "{pos_r[:90]}"')
        if neg_r:
            lines.append(f'Sample (-): "{neg_r[:90]}"')
        lines.append("")
    else:
        lines.append("=== CUSTOMER SENTIMENT ===")
        lines.append("Not available (tool skipped or failed).")
        lines.append("")

    # ── Trend data ────────────────────────────────────────────────────────────
    trends = context.get_tool_data("trend_analyzer")
    if trends:
        lines.append("=== MARKET TRENDS ===")
        lines.append(
            f"Direction: {trends['trend_direction']} "
            f"(momentum {trends['momentum_score']:.2f}/1.00)"
        )
        if trends.get("seasonal_pattern"):
            lines.append(f"Seasonal: {trends['seasonal_pattern']}")
        forecast = trends["forecast_summary"][:200]
        lines.append(f"Forecast: {forecast}")
        lines.append("")

    # ── Response schema ───────────────────────────────────────────────────────
    lines.append("Respond with a JSON object matching this schema exactly:")
    lines.append(_SYNTHESIS_SCHEMA)

    return "\n".join(lines)


def build_deep_synthesis_prompt(context: "AnalysisContext", competitive_context: str = "") -> str:
    """
    Extended prompt for deep analysis mode.

    Builds on the standard prompt but requests a richer output:
    - Structured recommendations with priority (high/medium/low) and rationale
    - Key market risks (max 3, grounded in the data)
    - Market opportunities (max 3, actionable)

    If an intermediate competitive_context string was produced by a prior LLM
    enrichment pass, it is injected as an additional input section so the final
    synthesis can build on those pre-extracted signals.
    """
    # Start from the standard compressed data block (reuse existing logic)
    base = build_synthesis_prompt(context)
    # Strip the trailing schema instruction — we replace it with the deep schema
    base = base[: base.rfind("Respond with a JSON object")].rstrip()

    lines = [base, ""]

    # ── Inject intermediate competitive signals if available ──────────────────
    if competitive_context:
        lines.append("=== PRE-EXTRACTED COMPETITIVE SIGNALS ===")
        lines.append(competitive_context)
        lines.append("")

    # ── Deep mode instructions ────────────────────────────────────────────────
    lines.append("=== DEEP ANALYSIS INSTRUCTIONS ===")
    lines.append(
        "This is a DEEP analysis. In addition to the standard summary and recommendations, "
        "you must produce a deep_analysis section containing:"
    )
    lines.append("- key_risks: up to 3 specific risks grounded in the data (not generic statements)")
    lines.append("- market_opportunities: up to 3 concrete opportunities tied to the data")
    lines.append(
        "- enriched_recommendations: up to 5 recommendations each with a priority "
        "(high/medium/low) and a one-sentence rationale citing a specific data point"
    )
    lines.append("")
    lines.append("Respond with a JSON object matching this schema exactly:")
    lines.append(_DEEP_SYNTHESIS_SCHEMA)

    return "\n".join(lines)
