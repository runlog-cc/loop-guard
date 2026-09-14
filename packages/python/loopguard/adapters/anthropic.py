"""Anthropic Python SDK adapter for Loop-Guard."""

import functools
import inspect
from typing import Any, Dict, Optional

from loopguard.core import CircuitBreaker, TripReason
from loopguard.budget import get_pricing_for_model


def wrap_anthropic(client: Any, guard: CircuitBreaker) -> Any:
    """
    Wraps an Anthropic client instance with Loop-Guard circuit-breaker monitoring.
    Drop-in:
        import anthropic
        from loopguard import CircuitBreaker, wrap_anthropic

        guard = CircuitBreaker()
        client = wrap_anthropic(anthropic.Anthropic(), guard)
    """
    if hasattr(client, "messages"):
        orig_create = client.messages.create
        is_async = inspect.iscoroutinefunction(orig_create)

        @functools.wraps(orig_create)
        def guarded_create(*args, **kwargs):
            if is_async:
                raise TypeError("Loop-Guard does not support asynchronous Anthropic clients; use explicit lifecycle calls.")
            if kwargs.get("stream"):
                raise ValueError("Loop-Guard does not support streaming Anthropic responses; use explicit lifecycle calls.")
            if not guard._request_lock.acquire(blocking=False):
                raise RuntimeError("Overlapping model requests are unsupported per guard")
            response_received = False
            try:
                blocked = guard.ensure_active()
                if guard.state.value == "tripped":
                    return blocked
                model = kwargs.get("model", "claude-3-5-sonnet")

                get_pricing_for_model(model)
                response = orig_create(*args, **kwargs)
                response_received = True
                if inspect.isawaitable(response):
                    if hasattr(response, "close"): response.close()
                    raise TypeError("Asynchronous provider responses are unsupported")

                # Record token usage
                usage = getattr(response, "usage", None)
                if usage and getattr(usage, "cache_creation_input_tokens", 0):
                    raise ValueError("Cache creation billing unsupported; use explicit normalized usage")
                if usage:
                    guard.record_usage(
                        prompt_tokens=getattr(usage, "input_tokens", 0) + getattr(usage, "cache_read_input_tokens", 0),
                        completion_tokens=getattr(usage, "output_tokens", 0),
                        model=model,
                        cached_tokens=getattr(usage, "cache_read_input_tokens", 0),
                    )

                # Intercept tool use blocks
                content = getattr(response, "content", []) or []
                for block in content:
                    block_type = getattr(block, "type", "")
                    if block_type == "tool_use":
                        tool_name = getattr(block, "name", "unknown")
                        tool_input = getattr(block, "input", {})
                        fallback = guard.observe_tool_request(tool_name=tool_name, arguments=tool_input)
                        if fallback is not None:
                            return fallback

                return response
            except Exception:
                if response_received and guard.state.value != "tripped":
                    guard._trip(TripReason.MANUAL_HALT, {"error": "Response accounting or observation failed"})
                raise
            finally:
                guard._request_lock.release()

        client.messages.create = guarded_create

    def unsupported(*args, **kwargs):
        raise TypeError("Loop-Guard does not support this API or streaming helper; use explicit lifecycle calls")
    endpoint = getattr(client, "messages", None)
    if endpoint is not None and hasattr(endpoint, "stream"):
        endpoint.stream = unsupported

    return client
