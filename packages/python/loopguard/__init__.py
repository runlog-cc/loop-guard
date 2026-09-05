"""Loop-Guard: Real-time circuit breaker and loop prevention for AI agents."""

__version__ = "0.1.0"

from loopguard.alerts import AlertDispatcher
from loopguard.budget import BudgetTracker, ModelPricing, get_pricing_for_model
from loopguard.core import (
    CircuitBreaker,
    CircuitState,
    CycleDetector,
    SignatureHasher,
    ToolCallEvent,
    TripPolicy,
    TripReason,
)
from loopguard.exceptions import (
    BudgetExceededError,
    CircuitTrippedError,
    LoopGuardException,
    MaxDepthExceededError,
    RepetitiveToolCallError,
)
from loopguard.adapters.openai import wrap_openai
from loopguard.adapters.anthropic import wrap_anthropic
from loopguard.adapters.langchain import LoopGuardCallbackHandler

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "TripPolicy",
    "TripReason",
    "ToolCallEvent",
    "SignatureHasher",
    "CycleDetector",
    "BudgetTracker",
    "ModelPricing",
    "get_pricing_for_model",
    "AlertDispatcher",
    "LoopGuardException",
    "CircuitTrippedError",
    "RepetitiveToolCallError",
    "BudgetExceededError",
    "MaxDepthExceededError",
    "wrap_openai",
    "wrap_anthropic",
    "LoopGuardCallbackHandler",
]
