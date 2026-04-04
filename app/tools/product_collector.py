import asyncio
from typing import TYPE_CHECKING, Any

from app.models.tool_outputs import CompetitorInfo, PlatformListing, ProductData, ToolResult
from app.tools.base import BaseTool

if TYPE_CHECKING:
    from app.orchestrator.context import AnalysisContext

# ── Mock catalog ──────────────────────────────────────────────────────────────
# Each entry mirrors what a real scraper would fetch from Amazon, eBay, and major retailers.
# Five real products cover the demo scenarios; all other queries fall through to the category-aware generic generator.

PRODUCT_CATALOG: dict[str, dict[str, Any]] = {
    "iphone 16 pro": {
        "platforms": [
            {"name": "Amazon", "price": 999.99, "rating": 4.5, "url": "mock://amazon/iphone16pro"},
            {"name": "Best Buy", "price": 999.00, "rating": 4.6, "url": "mock://bestbuy/iphone16pro"},
            {"name": "eBay (new)", "price": 979.00, "rating": 4.3, "url": "mock://ebay/iphone16pro"},
            {"name": "Apple Store", "price": 1_099.00, "rating": 4.7, "url": "mock://apple/iphone16pro"},
        ],
        "competitors": [
            {"name": "Samsung Galaxy S25 Ultra", "price": 1_299.99, "market_share_pct": 28.0},
            {"name": "Google Pixel 9 Pro", "price": 999.00, "market_share_pct": 8.0},
            {"name": "OnePlus 13", "price": 899.00, "market_share_pct": 3.5},
        ],
        "market_position": "premium",
    },
    "iphone 16": {
        "platforms": [
            {"name": "Amazon", "price": 799.99, "rating": 4.4, "url": "mock://amazon/iphone16"},
            {"name": "Best Buy", "price": 799.00, "rating": 4.5, "url": "mock://bestbuy/iphone16"},
            {"name": "eBay (new)", "price": 779.00, "rating": 4.2, "url": "mock://ebay/iphone16"},
        ],
        "competitors": [
            {"name": "Samsung Galaxy S25", "price": 799.99, "market_share_pct": 28.0},
            {"name": "Google Pixel 9", "price": 699.00, "market_share_pct": 7.5},
            {"name": "Motorola Edge 50", "price": 549.00, "market_share_pct": 2.5},
        ],
        "market_position": "premium",
    },
    "nike air max 270": {
        "platforms": [
            {"name": "Nike.com", "price": 150.00, "rating": 4.6, "url": "mock://nike/airmax270"},
            {"name": "Amazon", "price": 139.99, "rating": 4.4, "url": "mock://amazon/airmax270"},
            {"name": "Foot Locker", "price": 150.00, "rating": 4.5, "url": "mock://footlocker/airmax270"},
            {"name": "eBay (new)", "price": 129.00, "rating": 4.1, "url": "mock://ebay/airmax270"},
        ],
        "competitors": [
            {"name": "Adidas Ultraboost 24", "price": 190.00, "market_share_pct": 22.0},
            {"name": "New Balance 990v6", "price": 185.00, "market_share_pct": 8.0},
            {"name": "ASICS Gel-Nimbus 26", "price": 160.00, "market_share_pct": 6.5},
        ],
        "market_position": "mid-range",
    },
    "macbook pro 14": {
        "platforms": [
            {"name": "Apple Store", "price": 1_999.00, "rating": 4.8, "url": "mock://apple/mbp14"},
            {"name": "Amazon", "price": 1_949.99, "rating": 4.7, "url": "mock://amazon/mbp14"},
            {"name": "Best Buy", "price": 1_999.00, "rating": 4.7, "url": "mock://bestbuy/mbp14"},
        ],
        "competitors": [
            {"name": "Dell XPS 15", "price": 1_799.99, "market_share_pct": 12.0},
            {"name": "Lenovo ThinkPad X1 Carbon", "price": 1_649.00, "market_share_pct": 10.0},
            {"name": "Microsoft Surface Laptop 6", "price": 1_699.00, "market_share_pct": 7.0},
        ],
        "market_position": "premium",
    },
    "sony wh-1000xm5": {
        "platforms": [
            {"name": "Amazon", "price": 349.99, "rating": 4.6, "url": "mock://amazon/wh1000xm5"},
            {"name": "Best Buy", "price": 349.99, "rating": 4.6, "url": "mock://bestbuy/wh1000xm5"},
            {"name": "Sony Store", "price": 399.99, "rating": 4.7, "url": "mock://sony/wh1000xm5"},
            {"name": "eBay (new)", "price": 329.00, "rating": 4.3, "url": "mock://ebay/wh1000xm5"},
        ],
        "competitors": [
            {"name": "Apple AirPods Max", "price": 549.00, "market_share_pct": 18.0},
            {"name": "Bose QuietComfort 45", "price": 329.00, "market_share_pct": 15.0},
            {"name": "Sennheiser Momentum 4", "price": 349.95, "market_share_pct": 8.0},
        ],
        "market_position": "premium",
    },
}


# Category-level price anchors for the generic fallback
CATEGORY_DEFAULTS: dict[str, dict[str, Any]] = {
    "consumer electronics": {
        "price_base": 299.0, "price_variance": 150.0, "market_position": "mid-range",
        "platforms": ["Amazon", "Best Buy", "eBay", "Walmart"],
        "competitor_template": ["Competitor A Electronics", "Competitor B Tech", "Competitor C Gadgets"],
    },
    "athletic footwear": {
        "price_base": 120.0, "price_variance": 60.0, "market_position": "mid-range",
        "platforms": ["Nike.com", "Amazon", "Foot Locker", "DICK'S Sporting Goods"],
        "competitor_template": ["Adidas Runner Pro", "New Balance Classic", "Under Armour Speed"],
    },
    "home appliances": {
        "price_base": 499.0, "price_variance": 250.0, "market_position": "mid-range",
        "platforms": ["Amazon", "Home Depot", "Best Buy", "Costco"],
        "competitor_template": ["Brand A Appliances", "Brand B Home", "Brand C Living"],
    },
    "fashion": {
        "price_base": 80.0, "price_variance": 50.0, "market_position": "mid-range",
        "platforms": ["Amazon", "ASOS", "Zara Online", "H&M"],
        "competitor_template": ["StyleBrand A", "FashionLabel B", "TrendHouse C"],
    },
    "_default": {
        "price_base": 200.0, "price_variance": 100.0, "market_position": "mid-range",
        "platforms": ["Amazon", "eBay", "Walmart", "Target"],
        "competitor_template": ["Competitor Alpha", "Competitor Beta", "Competitor Gamma"],
    },
}


class ProductCollectorTool(BaseTool):
    """
    Simulates scraping product and competitor data from e-commerce platforms.

    Mock strategy:
    - Known products (5 entries) return hand-crafted realistic data.
    - Unknown products get a deterministic generic dataset derived from their category defaults,
      seeded by the product name, so the same request always produces the same numbers (reproducible demos).

    Ofcourse for production this would call a scraper service or APIs like:
    - SerpAPI,
    - RapidAPI's Amazon endpoint,
    - or a custom Playwright/Scrapy pipeline.
    """

    name = "product_collector"
    description = "Collects product prices, availability, and competitor listings from e-commerce platforms"

    async def execute(self, context: "AnalysisContext") -> ToolResult:
        await asyncio.sleep(0.1)  # simulate network I/O

        key = context.request.product_name.lower().strip()
        raw = PRODUCT_CATALOG.get(key)

        if raw is not None:
            product_data = self._from_catalog(raw, context.request.product_name, context.request.category)
        else:
            product_data = self._generate_generic(context.request.product_name, context.request.category)

        return ToolResult(
            tool_name=self.name,
            success=True,
            data=product_data.model_dump(),
        )

    def _from_catalog(self, raw: dict, product_name: str, category: str) -> ProductData:
        platforms = [PlatformListing(**p) for p in raw["platforms"]]
        competitors = [CompetitorInfo(**c) for c in raw["competitors"]]
        prices = [p.price for p in platforms]
        return ProductData(
            product_name=product_name,
            category=category,
            platforms=platforms,
            competitors=competitors,
            average_price=round(sum(prices) / len(prices), 2),
            price_range_min=min(prices),
            price_range_max=max(prices),
            market_position=raw["market_position"],
        )

    def _generate_generic(self, product_name: str, category: str) -> ProductData:
        seed = abs(hash(product_name.lower())) % 1000
        cat = CATEGORY_DEFAULTS.get(category.lower(), CATEGORY_DEFAULTS["_default"])

        base_price = cat["price_base"] + (seed / 1000) * cat["price_variance"]
        platform_names = cat["platforms"]
        platforms = [
            PlatformListing(
                name=pname,
                price=round(base_price * (0.92 + (abs(hash(pname + product_name)) % 100) / 600), 2),
                rating=round(3.8 + (abs(hash(pname)) % 20) / 100, 1),
            )
            for pname in platform_names
        ]
        competitors = [
            CompetitorInfo(
                name=cname,
                price=round(base_price * (0.80 + i * 0.1), 2),
                market_share_pct=round(15.0 - i * 3.5, 1),
            )
            for i, cname in enumerate(cat["competitor_template"])
        ]
        prices = [p.price for p in platforms]
        pos = cat["market_position"]
        if base_price < 100:
            pos = "budget"
        elif base_price > 500:
            pos = "premium"

        return ProductData(
            product_name=product_name,
            category=category,
            platforms=platforms,
            competitors=competitors,
            average_price=round(sum(prices) / len(prices), 2),
            price_range_min=min(prices),
            price_range_max=max(prices),
            market_position=pos,
        )
