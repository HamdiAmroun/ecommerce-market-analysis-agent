import asyncio
import logging

from app.config import Settings
from app.models.tool_outputs import ToolResult
from app.orchestrator.context import AnalysisContext
from app.orchestrator.pipeline import PipelineStep

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Responsible for running a single pipeline step reliably.

    Separating *how to run a tool* from *which tools to run* (pipeline.py)
    and *what to do with results* (agent.py) keeps each class small and
    single-purpose.

    Features:
    - Per-tool asyncio timeout (prevents a slow tool from blocking the pipeline)
    - Configurable retry count for transient failures
    - Structured logging with job_id for easy tracing in production logs
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run_step(self, step: PipelineStep, context: AnalysisContext) -> ToolResult:
        tool_name = step.tool.name
        job_id = context.job_id

        # ── Dynamic skip decision ─────────────────────────────────────────────
        # Evaluated after prior steps have written their results to the context,
        # so skip_if can inspect real intermediate data (not just the request).
        if step.skip_if is not None and step.skip_if(context):
            logger.info(
                "Tool skipped (condition met) | job=%s tool=%s",
                job_id,
                tool_name,
            )
            return ToolResult(
                tool_name=tool_name,
                success=False,
                skipped=True,
                data={},
            )

        for attempt in range(self.settings.max_retries + 1):
            if attempt > 0:
                logger.warning(
                    "Retrying tool (attempt %d/%d) | job=%s tool=%s",
                    attempt + 1,
                    self.settings.max_retries + 1,
                    job_id,
                    tool_name,
                )
            try:
                async with asyncio.timeout(self.settings.tool_timeout):
                    result = await step.tool._safe_execute(context)

                log_fn = logger.info if result.success else logger.warning
                log_fn(
                    "Tool finished | job=%s tool=%s success=%s time=%.1fms",
                    job_id,
                    tool_name,
                    result.success,
                    result.execution_time_ms,
                )
                return result

            except asyncio.TimeoutError:
                logger.error(
                    "Tool timed out (%.1fs) | job=%s tool=%s attempt=%d",
                    self.settings.tool_timeout,
                    job_id,
                    tool_name,
                    attempt + 1,
                )
                if attempt == self.settings.max_retries:
                    return ToolResult(
                        tool_name=tool_name,
                        success=False,
                        data={},
                        error=f"Tool timed out after {self.settings.tool_timeout}s",
                    )

        # Unreachable — satisfies the type checker
        raise RuntimeError("ToolExecutor retry loop exited without returning")
