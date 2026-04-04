from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    product_name: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Name of the product to analyse",
        examples=["iPhone 16 Pro", "Nike Air Max 270", "Sony WH-1000XM5"],
    )
    category: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Product category used to select sentiment profiles and trend patterns",
        examples=["consumer electronics", "athletic footwear", "home appliances"],
    )
    target_market: str = Field(
        default="global",
        max_length=100,
        description="Target market / geographic region for the analysis",
        examples=["US market", "European market", "global"],
    )
    analysis_depth: Literal["quick", "standard", "deep"] = Field(
        default="standard",
        description=(
            "quick — product data + trends only (fastest). "
            "standard — all 3 tools sequentially. "
            "deep — all 3 tools with LLM enrichment per step."
        ),
    )
