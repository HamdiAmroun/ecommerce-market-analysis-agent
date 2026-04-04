import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.routes import analysis, health
from app.config import settings
from app.store.job_store import InMemoryJobStore

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize shared resources on startup; clean up on shutdown."""
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)

    # Deferred import so the orchestrator module is only resolved after all app modules are ready
    # This avoids circular imports during testing.
    from app.llm.client import LLMClient
    from app.orchestrator.agent import MarketAnalysisAgent

    app.state.job_store = InMemoryJobStore()
    app.state.agent = MarketAnalysisAgent(
        settings=settings,
        llm_client=LLMClient(settings=settings),
    )

    if settings.llm_available:
        logger.info("LLM synthesis enabled  (model: %s)", settings.llm_model)
    else:
        logger.info("LLM synthesis disabled — using deterministic fallback (set GROQ_API_KEY to enable)")

    yield

    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "An e-commerce market analysis agent that orchestrates three specialised tools "
            "(product data collection, sentiment analysis, trend analysis) to produce "
            "structured business intelligence reports. "
            "Supports both LLM-powered synthesis and a deterministic fallback."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.include_router(health.router)
    app.include_router(analysis.router)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    return app


app = create_app()
