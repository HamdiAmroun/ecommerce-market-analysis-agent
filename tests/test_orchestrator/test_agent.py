from unittest.mock import AsyncMock, patch

import pytest

from app.models.tool_outputs import ToolResult
from app.orchestrator.agent import PipelineError


class TestAgentStandardFlow:
    async def test_full_run_returns_market_report(self, agent, sample_request):
        context = await agent.run(sample_request, job_id="test-001")
        assert context.report is not None

    async def test_report_has_executive_summary(self, agent, sample_request):
        context = await agent.run(sample_request, job_id="test-002")
        assert len(context.report.executive_summary) > 20

    async def test_report_has_recommendations(self, agent, sample_request):
        context = await agent.run(sample_request, job_id="test-003")
        assert len(context.report.recommendations) >= 1

    async def test_report_confidence_in_range(self, agent, sample_request):
        context = await agent.run(sample_request, job_id="test-004")
        assert 0.0 <= context.report.confidence_score <= 1.0

    async def test_fallback_generated_by(self, agent, sample_request):
        """Without API key the report must use 'fallback' synthesis."""
        context = await agent.run(sample_request, job_id="test-005")
        assert context.report.generated_by == "fallback"

    async def test_standard_depth_has_sentiment(self, agent, sample_request):
        context = await agent.run(sample_request, job_id="test-006")
        assert context.report.sentiment_analysis is not None

    async def test_context_has_all_three_tools(self, agent, sample_request):
        context = await agent.run(sample_request, job_id="test-007")
        assert "product_collector" in context.tool_results
        assert "sentiment_analyzer" in context.tool_results
        assert "trend_analyzer" in context.tool_results


class TestAgentQuickDepth:
    async def test_quick_depth_skips_sentiment(self, agent, quick_request):
        context = await agent.run(quick_request, job_id="test-q01")
        assert "sentiment_analyzer" not in context.tool_results

    async def test_quick_depth_has_product_and_trend(self, agent, quick_request):
        context = await agent.run(quick_request, job_id="test-q02")
        assert "product_collector" in context.tool_results
        assert "trend_analyzer" in context.tool_results

    async def test_quick_depth_sentiment_section_is_none(self, agent, quick_request):
        context = await agent.run(quick_request, job_id="test-q03")
        assert context.report.sentiment_analysis is None


class TestAgentRequiredToolFailure:
    async def test_required_tool_failure_raises_pipeline_error(self, agent, sample_request):
        with patch.object(
            agent.pipeline._product_collector,
            "_safe_execute",
            new_callable=AsyncMock,
        ) as mock_tool:
            mock_tool.return_value = ToolResult(
                tool_name="product_collector",
                success=False,
                error="Scraping service unavailable",
            )
            with pytest.raises(PipelineError, match="product_collector"):
                await agent.run(sample_request, job_id="test-fail-01")


class TestAgentOptionalToolFailure:
    async def test_optional_tool_failure_still_produces_report(self, agent, sample_request):
        with patch.object(
            agent.pipeline._sentiment_analyzer,
            "_safe_execute",
            new_callable=AsyncMock,
        ) as mock_tool:
            mock_tool.return_value = ToolResult(
                tool_name="sentiment_analyzer",
                success=False,
                error="Review API unreachable",
            )
            context = await agent.run(sample_request, job_id="test-opt-01")
        assert context.report is not None

    async def test_optional_tool_failure_adds_warning(self, agent, sample_request):
        with patch.object(
            agent.pipeline._sentiment_analyzer,
            "_safe_execute",
            new_callable=AsyncMock,
        ) as mock_tool:
            mock_tool.return_value = ToolResult(
                tool_name="sentiment_analyzer",
                success=False,
                error="Review API unreachable",
            )
            context = await agent.run(sample_request, job_id="test-opt-02")
        assert len(context.warnings) > 0

    async def test_optional_failure_sentiment_section_is_none(self, agent, sample_request):
        with patch.object(
            agent.pipeline._sentiment_analyzer,
            "_safe_execute",
            new_callable=AsyncMock,
        ) as mock_tool:
            mock_tool.return_value = ToolResult(
                tool_name="sentiment_analyzer",
                success=False,
                error="Review API unreachable",
            )
            context = await agent.run(sample_request, job_id="test-opt-03")
        assert context.report.sentiment_analysis is None


class TestAgentMetadata:
    async def test_metadata_records_tool_times(self, agent, sample_request):
        context = await agent.run(sample_request, job_id="test-meta-01")
        assert len(context.report.metadata.tool_execution_ms) > 0

    async def test_metadata_total_execution_positive(self, agent, sample_request):
        context = await agent.run(sample_request, job_id="test-meta-02")
        assert context.report.metadata.total_execution_ms > 0

    async def test_metadata_tools_succeeded_count(self, agent, sample_request):
        context = await agent.run(sample_request, job_id="test-meta-03")
        assert context.report.metadata.tools_succeeded >= 2
