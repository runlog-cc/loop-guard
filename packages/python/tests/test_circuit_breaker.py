"""Unit tests for Loop-Guard circuit breaker, cycle detection, and adapters."""

import unittest
from loopguard import (
    CircuitBreaker,
    CircuitState,
    TripPolicy,
    TripReason,
    SignatureHasher,
    CycleDetector,
    BudgetTracker,
    RepetitiveToolCallError,
    BudgetExceededError,
    MaxDepthExceededError,
    wrap_openai,
    wrap_anthropic,
    LoopGuardCallbackHandler,
)


class TestLoopGuard(unittest.TestCase):

    def test_signature_hasher(self):
        sig1 = SignatureHasher.compute("query_db", {"table": "users", "limit": 10})
        sig2 = SignatureHasher.compute("query_db", {"limit": 10, "table": "users"})
        self.assertEqual(sig1, sig2)
        self.assertTrue(sig1.startswith("query_db:"))

        sig3 = SignatureHasher.compute("query_db", {"limit": 20, "table": "users"})
        self.assertNotEqual(sig1, sig3)

        sig4 = SignatureHasher.compute("fetch_db", {"table": "users", "limit": 10})
        self.assertNotEqual(sig1, sig4)

    def test_cycle_detector(self):
        sigs = ["toolA:1", "toolB:2", "toolA:1", "toolB:2"]
        cycle = CycleDetector.detect_cycle(sigs, max_period=3, min_reps=2)
        self.assertIsNotNone(cycle)
        pattern, reps = cycle
        self.assertEqual(pattern, ["toolA:1", "toolB:2"])
        self.assertEqual(reps, 2)

        non_cycle = ["toolA:1", "toolB:2", "toolC:3", "toolD:4"]
        self.assertIsNone(CycleDetector.detect_cycle(non_cycle))

    def test_consecutive_retry_tripping(self):
        policy = TripPolicy(max_consecutive_retries=3, fallback_mode="exception")
        cb = CircuitBreaker(session_id="test-consecutive", policy=policy)

        # Call 1: OK
        self.assertIsNone(cb.before_tool_call("web_search", {"q": "langgraph tutorial"}))
        cb.after_tool_call("web_search", {"q": "langgraph tutorial"}, result="ConnectionTimeout", is_error=True)

        # Call 2: OK
        self.assertIsNone(cb.before_tool_call("web_search", {"q": "langgraph tutorial"}))
        cb.after_tool_call("web_search", {"q": "langgraph tutorial"}, result="ConnectionTimeout", is_error=True)

        # Call 3: Should trip
        with self.assertRaises(RepetitiveToolCallError) as ctx:
            cb.before_tool_call("web_search", {"q": "langgraph tutorial"})

        self.assertEqual(ctx.exception.reason, TripReason.CONSECUTIVE_RETRY.value)
        self.assertEqual(cb.state, CircuitState.TRIPPED)
        self.assertEqual(cb.trip_reason, TripReason.CONSECUTIVE_RETRY)

    def test_cycle_tripping(self):
        policy = TripPolicy(
            max_consecutive_retries=5,
            detect_cycles=True,
            max_cycle_length=2,
            min_cycle_repetitions=2,
            fallback_mode="exception",
        )
        cb = CircuitBreaker(session_id="test-cycle", policy=policy)

        cb.before_tool_call("toolA", {"arg": 1})
        cb.after_tool_call("toolA", {"arg": 1}, result="ok")

        cb.before_tool_call("toolB", {"arg": 2})
        cb.after_tool_call("toolB", {"arg": 2}, result="ok")

        cb.before_tool_call("toolA", {"arg": 1})
        cb.after_tool_call("toolA", {"arg": 1}, result="ok")

        with self.assertRaises(RepetitiveToolCallError) as ctx:
            cb.before_tool_call("toolB", {"arg": 2})

        self.assertEqual(ctx.exception.reason, TripReason.CYCLE_DETECTED.value)
        self.assertEqual(cb.state, CircuitState.TRIPPED)

    def test_budget_exceeded(self):
        policy = TripPolicy(max_cost_usd=0.05, fallback_mode="exception")
        cb = CircuitBreaker(session_id="test-budget", policy=policy)

        cost = cb.record_usage(prompt_tokens=100_000, completion_tokens=0, model="gpt-4o")
        self.assertGreater(cost, 0.05)
        self.assertEqual(cb.state, CircuitState.TRIPPED)

        with self.assertRaises(BudgetExceededError):
            cb.before_tool_call("query_user", {})

    def test_max_depth_exceeded(self):
        policy = TripPolicy(max_depth=3, fallback_mode="exception")
        cb = CircuitBreaker(session_id="test-depth", policy=policy)

        cb.before_tool_call("tool1", {})
        cb.after_tool_call("tool1", {})
        cb.before_tool_call("tool2", {})
        cb.after_tool_call("tool2", {})
        cb.before_tool_call("tool3", {})
        cb.after_tool_call("tool3", {})

        with self.assertRaises(MaxDepthExceededError):
            cb.before_tool_call("tool4", {})

        self.assertEqual(cb.state, CircuitState.TRIPPED)

    def test_synthetic_fallback_mode(self):
        policy = TripPolicy(
            max_consecutive_retries=2,
            fallback_mode="synthetic_response",
            fallback_message="Loop detected: stopped safely.",
        )
        cb = CircuitBreaker(session_id="test-fallback", policy=policy)

        cb.before_tool_call("scrape", {"url": "http://broken"})
        cb.after_tool_call("scrape", {"url": "http://broken"}, result="500")

        res = cb.before_tool_call("scrape", {"url": "http://broken"})
        self.assertIsInstance(res, dict)
        self.assertEqual(res["role"], "assistant")
        self.assertIn("Loop detected", res["content"])
        self.assertTrue(res["loopguard_status"]["tripped"])
        self.assertEqual(cb.state, CircuitState.TRIPPED)

    def test_langchain_callback_handler(self):
        policy = TripPolicy(max_consecutive_retries=2)
        cb = CircuitBreaker(session_id="test-lc", policy=policy)
        handler = LoopGuardCallbackHandler(cb)

        handler.on_tool_start(serialized={"name": "sql_query"}, input_str='{"query": "SELECT 1"}')
        handler.on_tool_end(output="result", name="sql_query")

        with self.assertRaises(RepetitiveToolCallError):
            handler.on_tool_start(serialized={"name": "sql_query"}, input_str='{"query": "SELECT 1"}')

    def test_openai_wrapper_interception(self):
        class DummyChoice:
            def __init__(self, name, args):
                class Fn:
                    def __init__(self, n, a):
                        self.name = n
                        self.arguments = a
                class TC:
                    def __init__(self, n, a):
                        self.function = Fn(n, a)
                class Msg:
                    def __init__(self, n, a):
                        self.tool_calls = [TC(n, a)]
                self.message = Msg(name, args)

        class DummyResponse:
            def __init__(self, name, args):
                self.choices = [DummyChoice(name, args)]
                self.usage = None

        class DummyCompletions:
            def create(self, *args, **kwargs):
                return DummyResponse("search_tool", '{"query": "test"}')

        class DummyChat:
            completions = DummyCompletions()

        class DummyClient:
            chat = DummyChat()

        policy = TripPolicy(max_consecutive_retries=2, fallback_mode="synthetic_response")
        cb = CircuitBreaker(session_id="test-openai", policy=policy)
        client = wrap_openai(DummyClient(), cb)

        r1 = client.chat.completions.create(model="gpt-4o", messages=[])
        self.assertIsInstance(r1, DummyResponse)
        cb.before_tool_call("search_tool", '{"query": "test"}')
        cb.after_tool_call("search_tool", '{"query": "test"}', result="empty")

        r2 = client.chat.completions.create(model="gpt-4o", messages=[])
        self.assertIsInstance(r2, dict)
        self.assertTrue(r2["loopguard_status"]["tripped"])

    def test_openai_wrapper_records_observed_requests_without_tool_results(self):
        class ToolResponse:
            def __init__(self, name, arguments):
                function = type("Function", (), {"name": name, "arguments": arguments})()
                tool_call = type("ToolCall", (), {"function": function})()
                message = type("Message", (), {"tool_calls": [tool_call]})()
                self.choices = [type("Choice", (), {"message": message})()]
                self.usage = None

        class Completions:
            calls = 0
            def create(self, *args, **kwargs):
                self.calls += 1
                return ToolResponse("lookup", '{"b": 2, "a": 1}')

        completions = Completions()
        client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
        guard = CircuitBreaker(policy=TripPolicy(max_consecutive_retries=3, fallback_mode="synthetic_response"))
        wrapped = wrap_openai(client, guard)

        self.assertIsInstance(wrapped.chat.completions.create(model="gpt-4o"), ToolResponse)
        self.assertIsInstance(wrapped.chat.completions.create(model="gpt-4o"), ToolResponse)
        blocked = wrapped.chat.completions.create(model="gpt-4o")

        self.assertTrue(blocked["loopguard_status"]["tripped"])
        self.assertEqual(completions.calls, 3)
        self.assertEqual(len(guard.history), 0)
        self.assertEqual(len(guard.signatures), 0)
        self.assertEqual(len(guard.observed_signatures), 3)

    def test_observed_request_depth_limit_blocks_distinct_requests(self):
        guard = CircuitBreaker(policy=TripPolicy(max_depth=2, fallback_mode="synthetic_response"))

        self.assertIsNone(guard.observe_tool_request("first", {}))
        self.assertIsNone(guard.observe_tool_request("second", {}))
        blocked = guard.observe_tool_request("third", {})

        self.assertTrue(blocked["loopguard_status"]["tripped"])
        self.assertEqual(guard.trip_reason, TripReason.MAX_DEPTH_EXCEEDED)
        self.assertEqual(len(guard.observed_signatures), 3)
        self.assertEqual(len(guard.signatures), 0)
        self.assertEqual(guard.current_depth, 0)

    def test_wrapper_stops_provider_after_observed_request_depth_trip(self):
        class Completions:
            calls = 0
            def create(self, *args, **kwargs):
                name = ("first", "second", "third")[self.calls]
                self.calls += 1
                function = type("Function", (), {"name": name, "arguments": "{}"})()
                tool_call = type("ToolCall", (), {"function": function})()
                message = type("Message", (), {"tool_calls": [tool_call]})()
                return type("Response", (), {"choices": [type("Choice", (), {"message": message})()], "usage": None})()

        completions = Completions()
        client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
        guard = CircuitBreaker(policy=TripPolicy(max_depth=2, fallback_mode="synthetic_response"))
        wrapped = wrap_openai(client, guard)

        wrapped.chat.completions.create(model="gpt-4o")
        wrapped.chat.completions.create(model="gpt-4o")
        self.assertTrue(wrapped.chat.completions.create(model="gpt-4o")["loopguard_status"]["tripped"])
        self.assertTrue(wrapped.chat.completions.create(model="gpt-4o")["loopguard_status"]["tripped"])

        self.assertEqual(completions.calls, 3)
        self.assertEqual(len(guard.observed_signatures), 3)

    def test_observed_request_and_actual_execution_have_separate_histories(self):
        guard = CircuitBreaker(policy=TripPolicy(max_consecutive_retries=2, fallback_mode="exception"))

        self.assertIsNone(guard.observe_tool_request("lookup", '{"id": 1}'))
        self.assertIsNone(guard.before_tool_call("lookup", {"id": 1}))
        guard.after_tool_call("lookup", {"id": 1}, result="ok")

        self.assertEqual(len(guard.observed_signatures), 1)
        self.assertEqual(len(guard.signatures), 1)
        self.assertEqual(guard.state, CircuitState.CLOSED)

    def test_anthropic_wrapper_blocks_alternating_observed_requests(self):
        class Messages:
            calls = 0
            def create(self, *args, **kwargs):
                name, payload = [("a", {"x": 1}), ("b", {"y": 2}), ("a", {"x": 1}), ("b", {"y": 2})][self.calls]
                self.calls += 1
                block = type("Block", (), {"type": "tool_use", "name": name, "input": payload})()
                return type("Response", (), {"content": [block], "usage": None})()

        messages = Messages()
        client = type("Client", (), {"messages": messages})()
        guard = CircuitBreaker(policy=TripPolicy(max_consecutive_retries=5, max_cycle_length=2, fallback_mode="synthetic_response"))
        wrapped = wrap_anthropic(client, guard)

        for _ in range(3):
            self.assertFalse(isinstance(wrapped.messages.create(model="claude-3-5-sonnet"), dict))
        blocked = wrapped.messages.create(model="claude-3-5-sonnet")

        self.assertTrue(blocked["loopguard_status"]["tripped"])
        self.assertEqual(messages.calls, 4)
        self.assertEqual(len(guard.history), 0)

    def test_wrapper_rejects_tripped_guard_without_provider_call(self):
        class Completions:
            calls = 0
            def create(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("provider must not be called")

        completions = Completions()
        client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
        guard = CircuitBreaker(policy=TripPolicy(max_cost_usd=0.01, fallback_mode="synthetic_response"))
        guard.record_usage(prompt_tokens=10_000, completion_tokens=0, model="gpt-4o")

        blocked = wrap_openai(client, guard).chat.completions.create(model="gpt-4o")

        self.assertTrue(blocked["loopguard_status"]["tripped"])
        self.assertEqual(completions.calls, 0)

    def test_openai_wrapper_rejects_streaming_and_async_clients_before_provider_call(self):
        class StreamingCompletions:
            calls = 0
            def create(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("provider must not be called")

        streaming = StreamingCompletions()
        stream_client = type("Client", (), {"chat": type("Chat", (), {"completions": streaming})()})()
        with self.assertRaisesRegex(ValueError, "streaming"):
            wrap_openai(stream_client, CircuitBreaker()).chat.completions.create(model="gpt-4o", stream=True)
        self.assertEqual(streaming.calls, 0)

        class AsyncCompletions:
            calls = 0
            async def create(self, *args, **kwargs):
                self.calls += 1

        asynchronous = AsyncCompletions()
        async_client = type("Client", (), {"chat": type("Chat", (), {"completions": asynchronous})()})()
        with self.assertRaisesRegex(TypeError, "asynchronous"):
            wrap_openai(async_client, CircuitBreaker()).chat.completions.create(model="gpt-4o")
        self.assertEqual(asynchronous.calls, 0)

    def test_anthropic_wrapper_rejects_streaming_and_async_clients_before_provider_call(self):
        class StreamingMessages:
            calls = 0
            def create(self, *args, **kwargs):
                self.calls += 1
                raise AssertionError("provider must not be called")

        streaming = StreamingMessages()
        stream_client = type("Client", (), {"messages": streaming})()
        with self.assertRaisesRegex(ValueError, "streaming"):
            wrap_anthropic(stream_client, CircuitBreaker()).messages.create(model="claude", stream=True)
        self.assertEqual(streaming.calls, 0)

        class AsyncMessages:
            calls = 0
            async def create(self, *args, **kwargs):
                self.calls += 1

        asynchronous = AsyncMessages()
        async_client = type("Client", (), {"messages": asynchronous})()
        with self.assertRaisesRegex(TypeError, "asynchronous"):
            wrap_anthropic(async_client, CircuitBreaker()).messages.create(model="claude")
        self.assertEqual(asynchronous.calls, 0)


if __name__ == "__main__":
    unittest.main()
