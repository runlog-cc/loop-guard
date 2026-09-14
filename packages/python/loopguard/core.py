"""Core circuit-breaker engine, signature hashing, cycle detection, and session state machine."""

import hashlib
import threading
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from loopguard.budget import BudgetTracker
from loopguard.exceptions import (
    BudgetExceededError,
    CircuitTrippedError,
    MaxDepthExceededError,
    RepetitiveToolCallError,
)


class CircuitState(str, Enum):
    CLOSED = "closed"        # Normal execution, traffic allowed
    TRIPPED = "tripped"      # Circuit tripped, further execution halted
    HALF_OPEN = "half_open"  # Recovery probe mode


class TripReason(str, Enum):
    CONSECUTIVE_RETRY = "consecutive_retry"
    CYCLE_DETECTED = "cycle_detected"
    BUDGET_EXCEEDED = "budget_exceeded"
    MAX_DEPTH_EXCEEDED = "max_depth_exceeded"
    MAX_PROVIDER_ATTEMPTS_EXCEEDED = "max_provider_attempts_exceeded"
    MANUAL_HALT = "manual_halt"


@dataclass
class TripPolicy:
    """Policy configurations governing when the circuit breaker trips."""
    max_consecutive_retries: int = 3
    max_depth: int = 20
    max_provider_attempts: int = 100
    loop_exempt_tools: List[str] = field(default_factory=list)
    max_cost_usd: float = 2.00
    detect_cycles: bool = True
    max_cycle_length: int = 4
    min_cycle_repetitions: int = 2
    fallback_mode: str = "exception"  # "exception" | "synthetic_response" | "custom"
    fallback_message: str = (
        "Loop-Guard Circuit Breaker Tripped: Safe execution halted. "
        "Repetitive tool execution or cost limit reached."
    )
    custom_fallback_handler: Optional[Callable[[Dict[str, Any]], Any]] = None


@dataclass
class ToolCallEvent:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    raw_args: Dict[str, Any] = field(default_factory=dict)
    signature: str = ""
    timestamp: float = field(default_factory=time.time)
    depth: int = 0
    is_error: bool = False
    result_preview: Optional[str] = None
    cost_usd: float = 0.0


class SignatureHasher:
    """Normalizes tool arguments into a deterministic signature hash."""

    @staticmethod
    def _normalize(obj: Any) -> Any:
        if isinstance(obj, dict):
            # Exclude known non-state dynamic fields if needed, sort keys
            return {k: SignatureHasher._normalize(v) for k, v in sorted(obj.items())}
        elif isinstance(obj, (list, tuple)):
            return [SignatureHasher._normalize(item) for item in obj]
        elif isinstance(obj, float):
            return round(obj, 6)
        return obj

    @classmethod
    def compute(cls, tool_name: str, args: Union[Dict[str, Any], str, None]) -> str:
        """
        Produce a deterministic signature: <tool_name>:<sha256_prefix>
        """
        parsed_args: Any = args
        if isinstance(args, str):
            try:
                parsed_args = json.loads(args)
            except Exception:
                parsed_args = args.strip()

        normalized = cls._normalize(parsed_args)
        canonical_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:16]
        return f"{tool_name}:{digest}"


class CycleDetector:
    """
    Detects repeating subsequences in a sequence of signatures.
    E.g. A -> B -> A -> B (period 2, 2 repetitions).
    """

    @staticmethod
    def detect_cycle(
        signatures: List[str],
        max_period: int = 4,
        min_reps: int = 2
    ) -> Optional[Tuple[List[str], int]]:
        """
        Check if the tail of `signatures` ends in a repeating period.
        Returns (cycle_pattern, repetition_count) if detected, else None.
        """
        n = len(signatures)
        if n < 4:
            return None

        # Try pattern lengths from 2 up to max_period
        for period in range(2, min(max_period + 1, (n // min_reps) + 1)):
            pattern = signatures[-period:]
            reps = 1
            idx = n - 2 * period
            while idx >= 0:
                chunk = signatures[idx : idx + period]
                if chunk == pattern:
                    reps += 1
                    idx -= period
                else:
                    break

            if reps >= min_reps:
                return (pattern, reps)

        return None


class CircuitBreaker:
    """
    Stateful circuit breaker guarding agent tool executions within a session.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        policy: Optional[TripPolicy] = None,
        on_trip: Optional[Callable[["CircuitBreaker", Dict[str, Any]], None]] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.session_id: str = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        self.policy: TripPolicy = policy or TripPolicy()
        if isinstance(self.policy.max_provider_attempts, bool) or not isinstance(self.policy.max_provider_attempts, int) or self.policy.max_provider_attempts < 1:
            raise ValueError("max_provider_attempts must be a positive finite integer")
        if not isinstance(self.policy.loop_exempt_tools, list) or not all(isinstance(n, str) for n in self.policy.loop_exempt_tools):
            raise ValueError("loop_exempt_tools must be a list of tool names")
        self.provider_attempts = 0
        self.accounted_provider_attempts = 0
        self.state: CircuitState = CircuitState.CLOSED
        self.trip_reason: Optional[TripReason] = None
        self.trip_details: Optional[Dict[str, Any]] = None
        self.history: List[ToolCallEvent] = []
        self.signatures: List[str] = []
        self.observed_signatures: List[str] = []
        self.budget: BudgetTracker = BudgetTracker(max_cost_usd=self.policy.max_cost_usd)
        self.current_depth: int = 0
        self._request_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._pending_signature: Optional[str] = None
        self.on_trip_callback = on_trip
        self.on_event_callback = on_event
        self.start_time: float = time.time()

    def record_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: Optional[str] = None,
        cached_tokens: int = 0,
        cost_usd: Optional[float] = None
    ) -> float:
        """Record token usage and check against budget ceiling."""
        total_cost, exceeded = self.budget.record_usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
            cached_tokens=cached_tokens,
            explicit_cost=cost_usd,
        )

        if exceeded and self.state == CircuitState.CLOSED:
            self._trip(
                reason=TripReason.BUDGET_EXCEEDED,
                details={
                    "total_cost_usd": total_cost,
                    "max_cost_usd": self.policy.max_cost_usd,
                    "model": model,
                }
            )

        return total_cost

    def ensure_active(self) -> Optional[Any]:
        """Block a new model request when this session has already tripped.

        This deliberately does not create a tool event or change depth: no tool
        execution has happened at this point.
        """
        if self.budget.is_exceeded() and self.state != CircuitState.TRIPPED:
            self._trip(TripReason.BUDGET_EXCEEDED, {})
        if self.state == CircuitState.TRIPPED:
            return self._handle_tripped(
                reason=self.trip_reason or TripReason.MANUAL_HALT,
                tool_name="model_request",
                signature="",
                details=self.trip_details or {},
            )
        return None

    def admit_provider_attempt(self):
        blocked = self.ensure_active()
        if self.state == CircuitState.TRIPPED:
            return blocked
        if self.provider_attempts >= self.policy.max_provider_attempts:
            self._trip(TripReason.MAX_PROVIDER_ATTEMPTS_EXCEEDED, {"provider_attempts": self.provider_attempts, "max_provider_attempts": self.policy.max_provider_attempts})
            return self.ensure_active()
        self.provider_attempts += 1
        return None

    def observe_tool_request(
        self,
        tool_name: str,
        arguments: Union[Dict[str, Any], str, None] = None,
    ) -> Optional[Any]:
        """Record a model-requested tool without claiming it executed.

        Adapters call this after receiving a provider response.  Applications
        still use before_tool_call/after_tool_call around real tool execution.
        """
        blocked = self.ensure_active()
        if self.state == CircuitState.TRIPPED:
            return blocked
        signature = SignatureHasher.compute(tool_name, arguments)
        self.observed_signatures.append(signature)
        observed_request_count = len(self.observed_signatures)
        if observed_request_count > self.policy.max_depth:
            self._trip(
                reason=TripReason.MAX_DEPTH_EXCEEDED,
                details={
                    "max_observed_tool_requests": self.policy.max_depth,
                    "observed_request_count": observed_request_count,
                    "observation": "model_requested_tool",
                },
                tool_name=tool_name,
                signature=signature,
            )
            return self._handle_tripped(
                reason=TripReason.MAX_DEPTH_EXCEEDED,
                tool_name=tool_name,
                signature=signature,
                details=self.trip_details or {},
            )
        if tool_name in self.policy.loop_exempt_tools:
            return None
        simulated_signatures = [s for s in self.observed_signatures if not any(s.startswith(n + ":") for n in self.policy.loop_exempt_tools)]
        consecutive_count = 0
        for sig in reversed(simulated_signatures):
            if sig == signature:
                consecutive_count += 1
            else:
                break
        if consecutive_count >= self.policy.max_consecutive_retries:
            self._trip(
                reason=TripReason.CONSECUTIVE_RETRY,
                details={
                    "consecutive_count": consecutive_count,
                    "threshold": self.policy.max_consecutive_retries,
                    "signature": signature,
                    "observation": "model_requested_tool",
                },
                tool_name=tool_name,
                signature=signature,
            )
            return self._handle_tripped(
                reason=TripReason.CONSECUTIVE_RETRY,
                tool_name=tool_name,
                signature=signature,
                details=self.trip_details or {},
                repetition_count=consecutive_count,
            )
        if self.policy.detect_cycles:
            cycle = CycleDetector.detect_cycle(
                simulated_signatures,
                max_period=self.policy.max_cycle_length,
                min_reps=self.policy.min_cycle_repetitions,
            )
            if cycle is not None:
                pattern, reps = cycle
                self._trip(
                    reason=TripReason.CYCLE_DETECTED,
                    details={
                        "cycle_pattern": pattern,
                        "repetitions": reps,
                        "signatures": simulated_signatures[-8:],
                        "observation": "model_requested_tool",
                    },
                    tool_name=tool_name,
                    signature=signature,
                )
                return self._handle_tripped(
                    reason=TripReason.CYCLE_DETECTED,
                    tool_name=tool_name,
                    signature=signature,
                    details=self.trip_details or {},
                    repetition_count=reps,
                )
        return None

    def before_tool_call(
        self,
        tool_name: str,
        arguments: Union[Dict[str, Any], str, None] = None,
    ) -> Optional[Any]:
        """
        Inspect a pending tool call before execution.
        If circuit is already tripped or this call triggers a trip,
        either raises an exception or returns a fallback response according to policy.
        """
        if self._pending_signature is not None:
            raise RuntimeError("Overlapping tool calls are unsupported; complete the pending call first")
        blocked = self.ensure_active()
        if self.state == CircuitState.TRIPPED: return blocked
        self.current_depth += 1
        signature = SignatureHasher.compute(tool_name, arguments)

        # Check if already tripped
        if self.state == CircuitState.TRIPPED:
            return self._handle_tripped(
                reason=self.trip_reason or TripReason.MANUAL_HALT,
                tool_name=tool_name,
                signature=signature,
                details=self.trip_details or {},
            )

        # Check max depth
        if self.current_depth > self.policy.max_depth:
            self._trip(
                reason=TripReason.MAX_DEPTH_EXCEEDED,
                details={"max_depth": self.policy.max_depth, "current_depth": self.current_depth},
                tool_name=tool_name,
                signature=signature,
            )
            return self._handle_tripped(
                reason=TripReason.MAX_DEPTH_EXCEEDED,
                tool_name=tool_name,
                signature=signature,
                details=self.trip_details or {},
            )

        if tool_name in self.policy.loop_exempt_tools:
            self._pending_signature = signature
            return None

        # Check consecutive identical retries
        simulated_signatures = [s for s in self.signatures + [signature] if not any(s.startswith(n + ":") for n in self.policy.loop_exempt_tools)]
        consecutive_count = 0
        for sig in reversed(simulated_signatures):
            if sig == signature:
                consecutive_count += 1
            else:
                break

        if consecutive_count >= self.policy.max_consecutive_retries:
            self._trip(
                reason=TripReason.CONSECUTIVE_RETRY,
                details={
                    "consecutive_count": consecutive_count,
                    "threshold": self.policy.max_consecutive_retries,
                    "signature": signature,
                },
                tool_name=tool_name,
                signature=signature,
            )
            return self._handle_tripped(
                reason=TripReason.CONSECUTIVE_RETRY,
                tool_name=tool_name,
                signature=signature,
                details=self.trip_details or {},
                repetition_count=consecutive_count,
            )

        # Check alternating cycles (A -> B -> A -> B)
        if self.policy.detect_cycles:
            cycle = CycleDetector.detect_cycle(
                simulated_signatures,
                max_period=self.policy.max_cycle_length,
                min_reps=self.policy.min_cycle_repetitions,
            )
            if cycle is not None:
                pattern, reps = cycle
                self._trip(
                    reason=TripReason.CYCLE_DETECTED,
                    details={
                        "cycle_pattern": pattern,
                        "repetitions": reps,
                        "signatures": simulated_signatures[-8:],
                    },
                    tool_name=tool_name,
                    signature=signature,
                )
                return self._handle_tripped(
                    reason=TripReason.CYCLE_DETECTED,
                    tool_name=tool_name,
                    signature=signature,
                    details=self.trip_details or {},
                    repetition_count=reps,
                )

        # Approved to proceed
        self._pending_signature = signature
        return None

    def after_tool_call(
        self,
        tool_name: str,
        arguments: Union[Dict[str, Any], str, None] = None,
        result: Any = None,
        is_error: bool = False,
        cost_usd: float = 0.0,
    ) -> ToolCallEvent:
        from loopguard.budget import validate_number
        validate_number(cost_usd, "cost_usd")
        if self._pending_signature is None:
            raise RuntimeError("after_tool_call requires an admitted before_tool_call")
        if not self._pending_signature.startswith(tool_name + ":"):
            raise RuntimeError("Tool completion does not match pending call")
        if arguments is not None:
            signature = SignatureHasher.compute(tool_name, arguments)
        elif self._pending_signature is not None:
            signature = self._pending_signature
            self._pending_signature = None
        else:
            signature = SignatureHasher.compute(tool_name, None)
        if signature != self._pending_signature and self._pending_signature is not None:
            raise RuntimeError("Tool arguments do not match pending call")
        self._pending_signature = None
        self.record_usage(0, 0, cost_usd=cost_usd)
        self.signatures.append(signature)

        preview = str(result)[:200] if result is not None else None
        event = ToolCallEvent(
            tool_name=tool_name,
            raw_args=arguments if isinstance(arguments, dict) else {"raw": arguments},
            signature=signature,
            depth=self.current_depth,
            is_error=is_error,
            result_preview=preview,
            cost_usd=cost_usd,
        )
        self.history.append(event)

        if self.on_event_callback:
            try:
                self.on_event_callback(self.to_dict())
            except Exception:
                pass

        return event

    def _trip(
        self,
        reason: TripReason,
        details: Dict[str, Any],
        tool_name: Optional[str] = None,
        signature: Optional[str] = None,
    ):
        """Set state to TRIPPED and notify callbacks."""
        self.state = CircuitState.TRIPPED
        self.trip_reason = reason
        self.trip_details = details
        details["reason"] = reason.value if hasattr(reason, "value") else str(reason)
        details["tool_name"] = tool_name
        details["signature"] = signature
        details["depth"] = self.current_depth
        details["cost_usd"] = self.budget.total_cost_usd

        if self.on_trip_callback:
            try:
                self.on_trip_callback(self, details)
            except Exception:
                pass

        if self.on_event_callback:
            try:
                self.on_event_callback(self.to_dict())
            except Exception:
                pass

    def _handle_tripped(
        self,
        reason: TripReason,
        tool_name: str,
        signature: str,
        details: Dict[str, Any],
        repetition_count: int = 0,
    ) -> Any:
        """Dispatch fallback response or raise specific typed error."""
        if self.policy.fallback_mode == "synthetic_response":
            return {
                "role": "assistant",
                "content": self.policy.fallback_message,
                "loopguard_status": {
                    "tripped": True,
                    "reason": reason.value,
                    "session_id": self.session_id,
                    "cost_usd": self.budget.total_cost_usd,
                },
            }
        elif self.policy.fallback_mode == "custom" and self.policy.custom_fallback_handler:
            return self.policy.custom_fallback_handler(details)

        # Default: raise exception
        msg = f"[Loop-Guard] Trip activated: {reason.value}. Session {self.session_id} halted. Detail: {details}"
        if reason == TripReason.CONSECUTIVE_RETRY or reason == TripReason.CYCLE_DETECTED:
            raise RepetitiveToolCallError(
                message=msg,
                session_id=self.session_id,
                reason=reason.value,
                tool_name=tool_name,
                signature=signature,
                repetition_count=repetition_count,
                current_depth=self.current_depth,
                cost_usd=self.budget.total_cost_usd,
                metadata=details,
            )
        elif reason == TripReason.BUDGET_EXCEEDED:
            raise BudgetExceededError(
                message=msg,
                session_id=self.session_id,
                reason=reason.value,
                tool_name=tool_name,
                signature=signature,
                current_depth=self.current_depth,
                cost_usd=self.budget.total_cost_usd,
                metadata=details,
            )
        elif reason == TripReason.MAX_DEPTH_EXCEEDED:
            raise MaxDepthExceededError(
                message=msg,
                session_id=self.session_id,
                reason=reason.value,
                tool_name=tool_name,
                signature=signature,
                current_depth=self.current_depth,
                cost_usd=self.budget.total_cost_usd,
                metadata=details,
            )
        else:
            raise CircuitTrippedError(
                message=msg,
                session_id=self.session_id,
                reason=reason.value,
                tool_name=tool_name,
                signature=signature,
                current_depth=self.current_depth,
                cost_usd=self.budget.total_cost_usd,
                metadata=details,
            )

    def reset(self):
        """Reset breaker to CLOSED state."""
        if self.budget.is_exceeded():
            raise RuntimeError("Cannot reset an exhausted budget; create a new session")
        if self._pending_signature is not None or self._request_lock.locked():
            raise RuntimeError("Cannot reset while a call is in flight")
        self.state = CircuitState.CLOSED
        self.trip_reason = None
        self.trip_details = None
        self.signatures.clear()
        self.observed_signatures.clear()
        self.history.clear()
        self.current_depth = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize full session status for telemetry and dashboard."""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "trip_reason": self.trip_reason.value if self.trip_reason else None,
            "trip_details": self.trip_details,
            "provider_attempts": self.provider_attempts,
            "unaccounted_provider_attempts": self.provider_attempts - self.accounted_provider_attempts,
            "max_provider_attempts": self.policy.max_provider_attempts,
            "current_depth": self.current_depth,
            "max_depth": self.policy.max_depth,
            "budget": self.budget.get_summary(),
            "history_count": len(self.history),
            "observed_request_count": len(self.observed_signatures),
            "recent_signatures": self.signatures[-10:],
            "recent_observed_signatures": self.observed_signatures[-10:],
            "elapsed_seconds": round(time.time() - self.start_time, 2),
            "history": [
                {
                    "id": h.id,
                    "tool_name": h.tool_name,
                    "signature": h.signature,
                    "raw_args": h.raw_args,
                    "depth": h.depth,
                    "is_error": h.is_error,
                    "timestamp": h.timestamp,
                    "result_preview": h.result_preview,
                }
                for h in self.history[-15:]
            ],
        }


def _serialized(method):
    def wrapped(self, *args, **kwargs):
        with self._lifecycle_lock:
            return method(self, *args, **kwargs)
    return wrapped

for _method in ("before_tool_call", "after_tool_call", "reset", "record_usage"):
    setattr(CircuitBreaker, _method, _serialized(getattr(CircuitBreaker, _method)))
