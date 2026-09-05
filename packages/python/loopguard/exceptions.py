"""Loop-Guard exception definitions."""

from typing import Optional, Dict, Any


class LoopGuardException(Exception):
    """Base exception for all Loop-Guard errors."""
    pass


class CircuitTrippedError(LoopGuardException):
    """Raised when the circuit breaker trips due to repetitive loops, budget limits, or depth."""

    def __init__(
        self,
        message: str,
        session_id: str,
        reason: str,
        tool_name: Optional[str] = None,
        signature: Optional[str] = None,
        repetition_count: int = 0,
        current_depth: int = 0,
        cost_usd: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.session_id = session_id
        self.reason = reason
        self.tool_name = tool_name
        self.signature = signature
        self.repetition_count = repetition_count
        self.current_depth = current_depth
        self.cost_usd = cost_usd
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": "CircuitTrippedError",
            "message": str(self),
            "session_id": self.session_id,
            "reason": self.reason,
            "tool_name": self.tool_name,
            "signature": self.signature,
            "repetition_count": self.repetition_count,
            "current_depth": self.current_depth,
            "cost_usd": self.cost_usd,
            "metadata": self.metadata,
        }


class RepetitiveToolCallError(CircuitTrippedError):
    """Raised when consecutive or cycling repetitive tool calls exceed the threshold."""
    pass


class BudgetExceededError(CircuitTrippedError):
    """Raised when the session cost exceeds the hard per-session dollar ceiling."""
    pass


class MaxDepthExceededError(CircuitTrippedError):
    """Raised when agent execution depth exceeds the maximum recursion limit."""
    pass
