"""OpenAI Python SDK adapter for Loop-Guard."""

import functools
import inspect
import json
from typing import Any, Callable, Dict, Optional, Union

from loopguard.core import CircuitBreaker, TripReason
from loopguard.budget import get_pricing_for_model


def wrap_openai(client: Any, guard: CircuitBreaker) -> Any:
    """
    Wraps an OpenAI client instance (synchronous, non-streaming) with Loop-Guard circuit-breaker monitoring.
    Drop-in:
        from openai import OpenAI
        from loopguard import CircuitBreaker, wrap_openai

        guard = CircuitBreaker()
        client = wrap_openai(OpenAI(), guard)
    """
    # Wrap sync client
    if hasattr(client, "chat") and hasattr(client.chat, "completions"):
        orig_create = client.chat.completions.create
        is_async = inspect.iscoroutinefunction(orig_create)

        @functools.wraps(orig_create)
        def guarded_create(*args, **kwargs):
            if is_async:
                raise TypeError("Loop-Guard does not support asynchronous OpenAI clients; use explicit lifecycle calls.")
            if kwargs.get("stream"):
                raise ValueError("Loop-Guard does not support streaming OpenAI responses; use explicit lifecycle calls.")
            if not guard._request_lock.acquire(blocking=False):
                raise RuntimeError("Overlapping model requests are unsupported per guard")
            response_received = False
            try:
                blocked = guard.ensure_active()
                if guard.state.value == "tripped":
                    return blocked
                model = kwargs.get("model", "gpt-4o")

                get_pricing_for_model(model)
                # Execute API call
                get_pricing_for_model(model)
                response = orig_create(*args, **kwargs)
                response_received = True
                if inspect.isawaitable(response):
                    if hasattr(response, "close"): response.close()
                    raise TypeError("Asynchronous provider responses are unsupported")

                # Record usage tokens if available
                usage = getattr(response, "usage", None)
                if usage:
                    guard.record_usage(
                        prompt_tokens=getattr(usage, "prompt_tokens", 0),
                        completion_tokens=getattr(usage, "completion_tokens", 0),
                        model=model,
                        cached_tokens=getattr(
                            getattr(usage, "prompt_tokens_details", None),
                            "cached_tokens",
                            0,
                        ) if hasattr(usage, "prompt_tokens_details") else 0,
                    )

                # Inspect tool calls in response choices
                choices = getattr(response, "choices", [])
                for choice in choices:
                    message = getattr(choice, "message", None)
                    if not message:
                        continue

                    tool_calls = getattr(message, "tool_calls", None) or []
                    for tc in tool_calls:
                        fn = getattr(tc, "function", None)
                        if fn:
                            name = getattr(fn, "name", "unknown")
                            call_args = getattr(fn, "arguments", "{}")
                            # This is only an observed provider request.  The caller
                            # owns the actual before/after tool execution lifecycle.
                            fallback = guard.observe_tool_request(tool_name=name, arguments=call_args)
                            if fallback is not None:
                                return fallback

                return response
            except Exception:
                if response_received and guard.state.value != "tripped":
                    guard._trip(TripReason.MANUAL_HALT, {"error": "Response accounting or observation failed"})
                raise
            finally:
                guard._request_lock.release()

        client.chat.completions.create = guarded_create

    def unsupported(*args, **kwargs):
        raise TypeError("Loop-Guard does not support this API or streaming helper; use explicit lifecycle calls")
    if hasattr(client, "responses"):
        client.responses.create = unsupported
    endpoint = getattr(getattr(client, "chat", None), "completions", None)
    if endpoint is not None and hasattr(endpoint, "stream"):
        endpoint.stream = unsupported

    return client
