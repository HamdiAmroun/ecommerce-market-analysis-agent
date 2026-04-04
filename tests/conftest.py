import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.llm.client import LLMClient
from app.main import create_app
from app.models.requests import AnalysisRequest
from app.orchestrator.agent import MarketAnalysisAgent
from app.store.job_store import InMemoryJobStore


@pytest.fixture
def settings_no_llm() -> Settings:
    """Settings with no API key — forces deterministic fallback."""
    return Settings(groq_api_key=None, tool_timeout=5.0, max_retries=1)


@pytest.fixture
def llm_client_no_key(settings_no_llm: Settings) -> LLMClient:
    return LLMClient(settings=settings_no_llm)


@pytest.fixture
def agent(settings_no_llm: Settings, llm_client_no_key: LLMClient) -> MarketAnalysisAgent:
    return MarketAnalysisAgent(settings=settings_no_llm, llm_client=llm_client_no_key)


@pytest.fixture
def sample_request() -> AnalysisRequest:
    return AnalysisRequest(
        product_name="iPhone 16 Pro",
        category="consumer electronics",
        target_market="US market",
        analysis_depth="standard",
    )


@pytest.fixture
def quick_request() -> AnalysisRequest:
    return AnalysisRequest(
        product_name="Nike Air Max 270",
        category="athletic footwear",
        analysis_depth="quick",
    )


@pytest.fixture
def unknown_product_request() -> AnalysisRequest:
    return AnalysisRequest(
        product_name="XyloGadget Pro 3000",
        category="consumer electronics",
        analysis_depth="standard",
    )


@pytest.fixture
async def async_client():
    """HTTPX async test client wired to the FastAPI app.

    We bypass the lifespan and manually initialise app.state so that
    each test gets a clean, isolated job store.
    """
    from app.llm.client import LLMClient
    from app.orchestrator.agent import MarketAnalysisAgent

    app = create_app()

    test_settings = Settings(groq_api_key=None, tool_timeout=5.0, max_retries=1)
    app.state.job_store = InMemoryJobStore()
    app.state.agent = MarketAnalysisAgent(
        settings=test_settings,
        llm_client=LLMClient(settings=test_settings),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
