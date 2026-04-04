from fastapi import APIRouter

from app.config import settings
from app.models.responses import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="Service health check")
async def health() -> HealthResponse:
    """Returns service health and LLM availability status."""
    return HealthResponse(
        version=settings.app_version,
        llm_available=settings.llm_available,
        llm_model=settings.llm_model if settings.llm_available else None,
    )
