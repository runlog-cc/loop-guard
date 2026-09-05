"""Anthropic Python SDK adapter for Loop-Guard."""

import functools
from typing import Any, Dict, Optional

from loopguard.core import CircuitBreaker


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

        @functools.wraps(orig_create)
        def guarded_create(*args, **kwargs):
            model = kwargs.get("model", "claude-3-5-sonnet")

            response = orig_create(*args, **kwargs)

            # Record token usage
            usage = getattr(response, "usage", None)
            if usage:
                guard.record_usage(
                    prompt_tokens=getattr(usage, "input_tokens", 0),
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
                    fallback = guard.before_tool_call(tool_name=tool_name, arguments=tool_input)
                    if fallback is not None:
                        return fallback

            return response

        client.messages.create = guarded_create

    return client
