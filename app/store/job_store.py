import asyncio
import uuid
from datetime import datetime, timezone

from app.models.requests import AnalysisRequest
from app.models.responses import AnalysisResponse, JobStatus, MarketReport


class InMemoryJobStore:
    """
    Thread-safe in-memory store for analysis jobs.

    Why? Because:
    - No external dependencies (zero-config demo)
    - All operations are atomic due to the use of an asyncio.Lock
    - Sufficient for single-instance deployments

    BUT definitely in production, this will be replaced with Redis or PostgreSQL
    """

    def __init__(self) -> None:
        self._store: dict[str, AnalysisResponse] = {}
        self._lock = asyncio.Lock()

    async def create(self, request: AnalysisRequest) -> AnalysisResponse:
        job = AnalysisResponse(
            job_id=str(uuid.uuid4()),
            status=JobStatus.PENDING,
            product_name=request.product_name,
            category=request.category,
            target_market=request.target_market,
            analysis_depth=request.analysis_depth,
            created_at=datetime.now(timezone.utc),
        )
        async with self._lock:
            self._store[job.job_id] = job
        return job

    async def get(self, job_id: str) -> AnalysisResponse | None:
        async with self._lock:
            return self._store.get(job_id)

    async def set_running(self, job_id: str) -> None:
        async with self._lock:
            if job_id in self._store:
                self._store[job_id] = self._store[job_id].model_copy(
                    update={"status": JobStatus.RUNNING}
                )

    async def set_completed(self, job_id: str, report: MarketReport) -> None:
        async with self._lock:
            if job_id in self._store:
                self._store[job_id] = self._store[job_id].model_copy(
                    update={
                        "status": JobStatus.COMPLETED,
                        "report": report,
                        "completed_at": datetime.now(timezone.utc),
                    }
                )

    async def set_failed(self, job_id: str, error: str) -> None:
        async with self._lock:
            if job_id in self._store:
                self._store[job_id] = self._store[job_id].model_copy(
                    update={
                        "status": JobStatus.FAILED,
                        "error": error,
                        "completed_at": datetime.now(timezone.utc),
                    }
                )

    async def list_all(self) -> list[AnalysisResponse]:
        async with self._lock:
            return list(self._store.values())
