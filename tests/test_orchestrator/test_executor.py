import asyncio
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.models.requests import AnalysisRequest
from app.models.tool_outputs import ToolResult
from app.orchestrator.context import AnalysisContext
from app.orchestrator.executor import ToolExecutor
from app.orchestrator.pipeline import PipelineStep
from app.tools.product_collector import ProductCollectorTool


def _make_settings() -> Settings:
    return Settings(tool_timeout=2.0, max_retries=1)


def _make_context() -> AnalysisContext:
    return AnalysisContext(
        job_id="test-exec",
        request=AnalysisRequest(
            product_name="iPhone 16 Pro",
            category="consumer electronics",
        ),
    )


class TestToolExecutorSuccess:
    async def test_successful_tool_returns_result(self):
        executor = ToolExecutor(_make_settings())
        tool = ProductCollectorTool()
        step = PipelineStep(tool=tool, required=True)
        ctx = _make_context()

        result = await executor.run_step(step, ctx)
        assert result.success is True
        assert result.tool_name == "product_collector"

    async def test_result_has_execution_time(self):
        executor = ToolExecutor(_make_settings())
        tool = ProductCollectorTool()
        step = PipelineStep(tool=tool, required=True)
        ctx = _make_context()

        result = await executor.run_step(step, ctx)
        assert result.execution_time_ms > 0


class TestToolExecutorTimeout:
    async def test_timeout_returns_failure(self):
        settings = Settings(tool_timeout=0.01, max_retries=0)  # 10ms timeout
        executor = ToolExecutor(settings)

        # Create a tool that always times out
        tool = ProductCollectorTool()

        async def slow_execute(ctx):
            await asyncio.sleep(1.0)
            return ToolResult(tool_name="product_collector", success=True, data={})

        step = PipelineStep(tool=tool, required=True)
        ctx = _make_context()

        with patch.object(tool, "_safe_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = asyncio.TimeoutError
            result = await executor.run_step(step, ctx)

        assert result.success is False
        assert "timed out" in result.error.lower()

    async def test_timeout_error_message_mentions_duration(self):
        settings = Settings(tool_timeout=5.0, max_retries=0)
        executor = ToolExecutor(settings)
        tool = ProductCollectorTool()
        step = PipelineStep(tool=tool, required=True)
        ctx = _make_context()

        with patch.object(tool, "_safe_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = asyncio.TimeoutError
            result = await executor.run_step(step, ctx)

        assert "5.0" in result.error


class TestToolExecutorRetry:
    async def test_retry_on_timeout_then_success(self):
        """Executor retries when a tool times out, succeeding on the second attempt."""
        settings = Settings(tool_timeout=5.0, max_retries=2)
        executor = ToolExecutor(settings)
        tool = ProductCollectorTool()
        step = PipelineStep(tool=tool, required=True)
        ctx = _make_context()

        call_count = 0

        async def flaky_execute(ctx):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise asyncio.TimeoutError  # simulates a timeout on first attempt
            return ToolResult(tool_name="product_collector", success=True, data={"ok": True})

        with patch.object(tool, "_safe_execute", side_effect=flaky_execute):
            result = await executor.run_step(step, ctx)

        assert result.success is True
        assert call_count == 2

    async def test_failed_result_returned_without_retry(self):
        """A tool returning success=False is returned immediately (not retried)."""
        settings = Settings(tool_timeout=5.0, max_retries=2)
        executor = ToolExecutor(settings)
        tool = ProductCollectorTool()
        step = PipelineStep(tool=tool, required=True)
        ctx = _make_context()

        call_count = 0

        async def always_fail(ctx):
            nonlocal call_count
            call_count += 1
            return ToolResult(tool_name="product_collector", success=False, error="permanent failure")

        with patch.object(tool, "_safe_execute", side_effect=always_fail):
            result = await executor.run_step(step, ctx)

        assert result.success is False
        assert call_count == 1  # not retried on failure-result
