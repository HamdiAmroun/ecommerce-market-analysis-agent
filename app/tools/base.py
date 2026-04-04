import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.models.tool_outputs import ToolResult

if TYPE_CHECKING:
    from app.orchestrator.context import AnalysisContext


class BaseTool(ABC):
    """
    Abstract base class for all analysis tools.

    Design decisions:
    - Tools receive a shared AnalysisContext (read-only access to the request and previously collected results).
    - Tools do NOT mutate the context. The orchestrator is responsible for accumulating results.
    - _safe_execute() wraps the abstract execute() with timing and error capture, so individual tools never need
      boilerplate try/except logic.
    """

    name: str
    description: str

    @abstractmethod
    async def execute(self, context: "AnalysisContext") -> ToolResult:
        """Perform the tool's analysis and return a ToolResult."""
        ...

    async def _safe_execute(self, context: "AnalysisContext") -> ToolResult:
        """Public execution entry point — adds timing and catches all errors."""
        start = time.perf_counter()
        try:
            result = await self.execute(context)
            result.execution_time_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                success=False,
                data={},
                error=str(exc),
                execution_time_ms=(time.perf_counter() - start) * 1000,
            )
