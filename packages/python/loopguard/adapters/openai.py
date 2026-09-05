"""OpenAI Python SDK adapter for Loop-Guard."""

import functools
import json
from typing import Any, Callable, Dict, Optional, Union

from loopguard.core import CircuitBreaker


def wrap_openai(client: Any, guard: CircuitBreaker) -> Any:
    """
    Wraps an OpenAI client instance (sync or async) with Loop-Guard circuit-breaker monitoring.
    Drop-in:
        from openai import OpenAI
        from loopguard import CircuitBreaker, wrap_openai

        guard = CircuitBreaker()
        client = wrap_openai(OpenAI(), guard)
    """
    # Wrap sync client
    if hasattr(client, "chat") and hasattr(client.chat, "completions"):
        orig_create = client.chat.completions.create

        @functools.wraps(orig_create)
        def guarded_create(*args, **kwargs):
            # Check model & calculate tokens / check breaker if previous calls tripped
            model = kwargs.get("model", "gpt-4o")

            # Execute API call
            response = orig_create(*args, **kwargs)

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
                        # Pre-check tool call against breaker
                        fallback = guard.before_tool_call(tool_name=name, arguments=call_args)
                        if fallback is not None:
                            # Replace choice message with fallback if synthetic
                            return fallback

            return response

        client.chat.completions.create = guarded_create

    return client
