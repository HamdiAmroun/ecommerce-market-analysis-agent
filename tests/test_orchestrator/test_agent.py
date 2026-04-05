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


class TestAgentDeepMode:
    async def test_deep_mode_returns_report(self, agent):
        from app.models.requests import AnalysisRequest
        req = AnalysisRequest(
            product_name="iPhone 16 Pro",
            category="consumer electronics",
            analysis_depth="deep",
        )
        context = await agent.run(req, job_id="test-deep-01")
        assert context.report is not None

    async def test_deep_mode_has_deep_analysis_section(self, agent):
        from app.models.requests import AnalysisRequest
        req = AnalysisRequest(
            product_name="iPhone 16 Pro",
            category="consumer electronics",
            analysis_depth="deep",
        )
        context = await agent.run(req, job_id="test-deep-02")
        # Without LLM key, falls back to deterministic deep analysis
        assert context.report.deep_analysis is not None

    async def test_deep_analysis_has_risks(self, agent):
        from app.models.requests import AnalysisRequest
        req = AnalysisRequest(
            product_name="iPhone 16 Pro",
            category="consumer electronics",
            analysis_depth="deep",
        )
        context = await agent.run(req, job_id="test-deep-03")
        assert len(context.report.deep_analysis.key_risks) >= 1

    async def test_deep_analysis_has_opportunities(self, agent):
        from app.models.requests import AnalysisRequest
        req = AnalysisRequest(
            product_name="iPhone 16 Pro",
            category="consumer electronics",
            analysis_depth="deep",
        )
        context = await agent.run(req, job_id="test-deep-04")
        assert len(context.report.deep_analysis.market_opportunities) >= 1

    async def test_deep_analysis_enriched_recommendations_have_priority(self, agent):
        from app.models.requests import AnalysisRequest
        req = AnalysisRequest(
            product_name="iPhone 16 Pro",
            category="consumer electronics",
            analysis_depth="deep",
        )
        context = await agent.run(req, job_id="test-deep-05")
        for rec in context.report.deep_analysis.enriched_recommendations:
            assert rec.priority in ("high", "medium", "low")
            assert len(rec.rationale) > 0

    async def test_standard_mode_has_no_deep_analysis(self, agent, sample_request):
        context = await agent.run(sample_request, job_id="test-deep-06")
        assert context.report.deep_analysis is None


class TestAgentDynamicSkip:
    async def test_unknown_product_skips_sentiment(self, agent, unknown_product_request):
        """Generic (non-catalog) product should trigger skip_if and omit sentiment."""
        context = await agent.run(unknown_product_request, job_id="test-skip-01")
        sentiment_result = context.tool_results.get("sentiment_analyzer")
        assert sentiment_result is not None
        assert sentiment_result.skipped is True

    async def test_skipped_tool_adds_warning(self, agent, unknown_product_request):
        context = await agent.run(unknown_product_request, job_id="test-skip-02")
        assert any("skipped" in w.lower() for w in context.warnings)

    async def test_skipped_tool_counted_in_metadata(self, agent, unknown_product_request):
        context = await agent.run(unknown_product_request, job_id="test-skip-03")
        assert context.report.metadata.tools_skipped == 1

    async def test_known_product_does_not_skip_sentiment(self, agent, sample_request):
        """Catalog product should NOT trigger the skip condition."""
        context = await agent.run(sample_request, job_id="test-skip-04")
        sentiment_result = context.tool_results.get("sentiment_analyzer")
        assert sentiment_result is not None
        assert sentiment_result.skipped is False
        assert sentiment_result.success is True
