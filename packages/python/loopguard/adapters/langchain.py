"""LangChain and LangGraph CallbackHandler adapter for Loop-Guard."""

from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from loopguard.core import CircuitBreaker


class LoopGuardCallbackHandler:
    """
    LangChain/LangGraph BaseCallbackHandler-compatible interceptor.
    
    Usage with LangGraph / LangChain:
        from loopguard import CircuitBreaker, LoopGuardCallbackHandler
        
        guard = CircuitBreaker()
        handler = LoopGuardCallbackHandler(guard)
        agent_executor.invoke({"input": "..."}, config={"callbacks": [handler]})
    """

    def __init__(self, guard: CircuitBreaker):
        self.guard = guard

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: Optional[UUID] = None,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        inputs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        tool_name = serialized.get("name", "tool") if serialized else "tool"
        args = inputs if inputs is not None else input_str

        # Check circuit breaker before tool runs
        fallback = self.guard.before_tool_call(tool_name=tool_name, arguments=args)
        return fallback

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: Optional[UUID] = None,
        parent_run_id: Optional[UUID] = None,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        tool_name = name or "tool"
        self.guard.after_tool_call(
            tool_name=tool_name,
            result=output,
            is_error=False,
        )

    def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: Optional[UUID] = None,
        parent_run_id: Optional[UUID] = None,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        tool_name = name or "tool"
        self.guard.after_tool_call(
            tool_name=tool_name,
            result=str(error),
            is_error=True,
        )

    def on_llm_end(self, response: Any, **kwargs: Any) -> Any:
        """Accumulate token spend if llm_output provides token_usage."""
        llm_output = getattr(response, "llm_output", None) or {}
        token_usage = llm_output.get("token_usage") or {}
        if token_usage:
            prompt_tokens = token_usage.get("prompt_tokens", 0)
            completion_tokens = token_usage.get("completion_tokens", 0)
            model_name = llm_output.get("model_name", "gpt-4o")
            self.guard.record_usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=model_name,
            )
