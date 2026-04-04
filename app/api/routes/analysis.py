import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.dependencies import AgentDep, JobStoreDep
from app.models.requests import AnalysisRequest
from app.models.responses import AnalysisResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analyze", tags=["Analysis"])


async def _run_analysis(agent, job_store, job_id: str, request: AnalysisRequest) -> None:
    """Background task: runs the agent and updates job state."""
    await job_store.set_running(job_id)
    try:
        context = await agent.run(request, job_id)
        await job_store.set_completed(job_id, context.report)
    except Exception as exc:
        logger.exception("Analysis failed for job %s", job_id)
        await job_store.set_failed(job_id, str(exc))


@router.post(
    "",
    response_model=AnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a market analysis request",
    description=(
        "Submits a new analysis job. Returns immediately with a job_id. "
        "Poll GET /analyze/{job_id} until status is 'completed' or 'failed'."
    ),
)
async def submit_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
    job_store: JobStoreDep,
    agent: AgentDep,
) -> AnalysisResponse:
    job = await job_store.create(request)
    background_tasks.add_task(_run_analysis, agent, job_store, job.job_id, request)
    return job


@router.get(
    "/{job_id}",
    response_model=AnalysisResponse,
    summary="Get analysis job status and results",
    description="Returns the current status of a job. When status='completed' the full report is included.",
)
async def get_analysis(job_id: str, job_store: JobStoreDep) -> AnalysisResponse:
    job = await job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


@router.get(
    "",
    response_model=list[AnalysisResponse],
    summary="List all analysis jobs",
    description="Returns all jobs in the in-memory store. Useful for demos and debugging.",
)
async def list_analyses(job_store: JobStoreDep) -> list[AnalysisResponse]:
    return await job_store.list_all()
