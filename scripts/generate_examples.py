"""
Generate example report JSON files and save them to examples/ with a datetime stamp.

Usage:
    python scripts/generate_examples.py

What it does:
  1. Runs the agent for iPhone 16 Pro (standard depth) using the deterministic
     fallback path — always works, no API key required.
  2. If GROQ_API_KEY is set in the environment, also runs a deep analysis using
     the LLM path and saves a second file.
  3. Saves each output to examples/<label>_<product_slug>_<YYYYMMDD_HHMMSS>.json

Old example files are NOT deleted — each run appends a new timestamped file so
the history is preserved. Delete old files manually if the examples/ folder grows.

Run this script any time the data model changes or after a prompt update to
regenerate reference output with current behaviour.
"""

import asyncio
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Allow running from the project root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings
from app.llm.client import LLMClient
from app.models.requests import AnalysisRequest
from app.models.responses import AnalysisResponse, JobStatus
from app.orchestrator.agent import MarketAnalysisAgent


def _slug(name: str) -> str:
    """Convert a product name to a safe filename fragment."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _build_response(request: AnalysisRequest, report, job_id: str) -> AnalysisResponse:
    """Assemble a full AnalysisResponse from a completed agent context."""
    now = datetime.now(timezone.utc)
    return AnalysisResponse(
        job_id=job_id,
        status=JobStatus.COMPLETED,
        product_name=request.product_name,
        category=request.category,
        target_market=request.target_market,
        analysis_depth=request.analysis_depth,
        created_at=now,
        completed_at=now,
        report=report,
    )


def _save(label: str, request: AnalysisRequest, report, timestamp: str) -> Path:
    """Serialize and write the response to examples/<label>_<slug>_<timestamp>.json."""
    examples_dir = Path(__file__).parent.parent / "examples"
    examples_dir.mkdir(exist_ok=True)

    job_id = str(uuid.uuid4())
    response = _build_response(request, report, job_id)

    filename = f"{label}_{_slug(request.product_name)}_{timestamp}.json"
    output_path = examples_dir / filename

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            json.loads(response.model_dump_json()),
            f,
            indent=2,
            ensure_ascii=False,
        )

    return output_path


async def generate(product_name: str, category: str, depth: str = "standard") -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'='*60}")
    print(f"Product  : {product_name}")
    print(f"Category : {category}")
    print(f"Depth    : {depth}")
    print(f"Timestamp: {timestamp}")

    # ── Fallback path (no API key) ────────────────────────────────────────────
    fallback_settings = Settings(groq_api_key=None, tool_timeout=10.0, max_retries=1)
    fallback_llm = LLMClient(settings=fallback_settings)
    fallback_agent = MarketAnalysisAgent(settings=fallback_settings, llm_client=fallback_llm)

    request = AnalysisRequest(
        product_name=product_name,
        category=category,
        analysis_depth=depth,
    )

    print("\n[1/2] Running fallback path (no LLM key)...")
    context = await fallback_agent.run(request, job_id=str(uuid.uuid4()))
    fallback_path = _save("fallback_report", request, context.report, timestamp)
    print(f"      Saved -> {fallback_path.relative_to(Path(__file__).parent.parent)}")
    print(f"      generated_by   : {context.report.generated_by}")
    print(f"      tools_succeeded: {context.report.metadata.tools_succeeded}")
    print(f"      tools_skipped  : {context.report.metadata.tools_skipped}")
    print(f"      confidence     : {context.report.confidence_score}")
    print(f"      has_deep       : {context.report.deep_analysis is not None}")

    # ── LLM path (only if API key is present) ────────────────────────────────
    llm_settings = Settings(tool_timeout=30.0, max_retries=1)
    if not llm_settings.llm_available:
        print("\n[2/2] LLM path skipped — GROQ_API_KEY not set.")
        print("      Set GROQ_API_KEY in your environment and re-run to generate the LLM example.")
        return

    llm_client = LLMClient(settings=llm_settings)
    llm_agent = MarketAnalysisAgent(settings=llm_settings, llm_client=llm_client)

    print("\n[2/2] Running LLM path (Groq)...")
    llm_context = await llm_agent.run(request, job_id=str(uuid.uuid4()))
    llm_path = _save("groq_llm_report", request, llm_context.report, timestamp)
    print(f"      Saved -> {llm_path.relative_to(Path(__file__).parent.parent)}")
    print(f"      generated_by   : {llm_context.report.generated_by}")
    print(f"      tools_succeeded: {llm_context.report.metadata.tools_succeeded}")
    print(f"      confidence     : {llm_context.report.confidence_score}")
    print(f"      has_deep       : {llm_context.report.deep_analysis is not None}")


async def main() -> None:
    print("Generating example reports...")

    # Standard depth — iPhone 16 Pro (catalog product, all 3 tools)
    await generate("iPhone 16 Pro", "consumer electronics", depth="standard")

    # Deep depth — MacBook Pro 14 (catalog product, deep_analysis section)
    await generate("MacBook Pro 14", "consumer electronics", depth="deep")

    print(f"\n{'='*60}")
    print("Done. Files saved to examples/")
    print("Tip: Run with GROQ_API_KEY set to also generate LLM-path examples.")


if __name__ == "__main__":
    asyncio.run(main())
