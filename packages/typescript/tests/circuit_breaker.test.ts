import { describe, expect, test } from "bun:test";
import {
  CircuitBreaker,
  SignatureHasher,
  CycleDetector,
  RepetitiveToolCallError,
  BudgetExceededError,
  MaxDepthExceededError,
  wrapOpenAI,
  wrapAnthropic,
} from "../src/index";

describe("Loop-Guard TypeScript SDK", () => {
  test("SignatureHasher generates deterministic signatures regardless of key order", () => {
    const s1 = SignatureHasher.compute("query_db", { limit: 10, table: "users" });
    const s2 = SignatureHasher.compute("query_db", { table: "users", limit: 10 });
    expect(s1).toBe(s2);
    expect(s1.startsWith("query_db:")).toBe(true);
  });

  test("CycleDetector detects alternating patterns", () => {
    const sigs = ["A:1", "B:2", "A:1", "B:2"];
    const cycle = CycleDetector.detectCycle(sigs, 3, 2);
    expect(cycle).not.toBeNull();
    expect(cycle?.pattern).toEqual(["A:1", "B:2"]);
    expect(cycle?.repetitions).toBe(2);
  });

  test("Consecutive retry threshold trips circuit breaker", () => {
    const guard = new CircuitBreaker({
      sessionId: "ts-test-consecutive",
      policy: { maxConsecutiveRetries: 3, fallbackMode: "exception" },
    });

    expect(guard.beforeToolCall("scrape", { url: "https://fail.com" })).toBeNull();
    guard.afterToolCall({ toolName: "scrape", args: { url: "https://fail.com" }, result: "500", isError: true });

    expect(guard.beforeToolCall("scrape", { url: "https://fail.com" })).toBeNull();
    guard.afterToolCall({ toolName: "scrape", args: { url: "https://fail.com" }, result: "500", isError: true });

    expect(() => {
      guard.beforeToolCall("scrape", { url: "https://fail.com" });
    }).toThrow(RepetitiveToolCallError);

    expect(guard.state).toBe("tripped");
    expect(guard.tripReason).toBe("consecutive_retry");
  });

  test("Alternating cycle trips circuit breaker", () => {
    const guard = new CircuitBreaker({
      sessionId: "ts-test-cycle",
      policy: {
        maxConsecutiveRetries: 5,
        detectCycles: true,
        maxCycleLength: 2,
        minCycleRepetitions: 2,
        fallbackMode: "exception",
      },
    });

    guard.beforeToolCall("toolA", { x: 1 });
    guard.afterToolCall({ toolName: "toolA", args: { x: 1 } });

    guard.beforeToolCall("toolB", { y: 2 });
    guard.afterToolCall({ toolName: "toolB", args: { y: 2 } });

    guard.beforeToolCall("toolA", { x: 1 });
    guard.afterToolCall({ toolName: "toolA", args: { x: 1 } });

    expect(() => {
      guard.beforeToolCall("toolB", { y: 2 });
    }).toThrow(RepetitiveToolCallError);

    expect(guard.state).toBe("tripped");
    expect(guard.tripReason).toBe("cycle_detected");
  });

  test("Budget ceiling exceeded trips breaker", () => {
    const guard = new CircuitBreaker({
      sessionId: "ts-test-budget",
      policy: { maxCostUsd: 0.1, fallbackMode: "exception" },
    });

    // 100,000 prompt tokens with gpt-4o ($2.50/M) = $0.25 (exceeds $0.10)
    const cost = guard.recordUsage({
      promptTokens: 100_000,
      completionTokens: 0,
      model: "gpt-4o",
    });

    expect(cost).toBeGreaterThan(0.1);
    expect(guard.state).toBe("tripped");
    expect(() => guard.beforeToolCall("call_db", {})).toThrow(BudgetExceededError);
  });

  test("Max recursion depth exceeded trips breaker", () => {
    const guard = new CircuitBreaker({
      sessionId: "ts-test-depth",
      policy: { maxDepth: 2, fallbackMode: "exception" },
    });

    guard.beforeToolCall("step1");
    guard.afterToolCall({ toolName: "step1" });

    guard.beforeToolCall("step2");
    guard.afterToolCall({ toolName: "step2" });

    expect(() => guard.beforeToolCall("step3")).toThrow(MaxDepthExceededError);
    expect(guard.state).toBe("tripped");
  });

  test("Synthetic fallback returns safe response without throwing", () => {
    const guard = new CircuitBreaker({
      sessionId: "ts-test-synthetic",
      policy: {
        maxConsecutiveRetries: 2,
        fallbackMode: "synthetic_response",
        fallbackMessage: "Agent paused safely.",
      },
    });

    guard.beforeToolCall("test", {});
    guard.afterToolCall({ toolName: "test", args: {} });

    const fallback = guard.beforeToolCall("test", {});
    expect(fallback).toBeDefined();
    expect(fallback.role).toBe("assistant");
    expect(fallback.content).toBe("Agent paused safely.");
    expect(fallback.loopguardStatus.tripped).toBe(true);
  });

  test("wrapOpenAI intercepts and triggers fallback", async () => {
    const guard = new CircuitBreaker({
      sessionId: "ts-test-wrap",
      policy: { maxConsecutiveRetries: 2, fallbackMode: "synthetic_response" },
    });

    const mockClient = {
      chat: {
        completions: {
          create: async () => ({
            choices: [
              {
                message: {
                  tool_calls: [
                    {
                      function: {
                        name: "fetch_data",
                        arguments: '{"id": 42}',
                      },
                    },
                  ],
                },
              },
            ],
            usage: { prompt_tokens: 10, completion_tokens: 20 },
          }),
        },
      },
    };

    const wrapped = wrapOpenAI(mockClient, guard);

    // Call 1: passes
    const res1 = await wrapped.chat.completions.create({ model: "gpt-4o" });
    expect(res1.choices).toBeDefined();
    guard.beforeToolCall("fetch_data", '{"id": 42}');
    guard.afterToolCall({ toolName: "fetch_data", args: '{"id": 42}' });

    // Call 2: repeated tool call -> returns synthetic fallback
    const res2 = await wrapped.chat.completions.create({ model: "gpt-4o" });
    expect(res2.loopguardStatus).toBeDefined();
    expect(res2.loopguardStatus.tripped).toBe(true);
  });

  test("wrapOpenAI records canonical observed requests without tool results", async () => {
    let calls = 0;
    const guard = new CircuitBreaker({ policy: { maxConsecutiveRetries: 3, fallbackMode: "synthetic_response" } });
    const wrapped = wrapOpenAI({ chat: { completions: { create: async () => {
      calls++;
      return { choices: [{ message: { tool_calls: [{ function: { name: "lookup", arguments: calls === 2 ? '{"a":1,"b":2}' : '{"b":2,"a":1}' } }] } }] };
    } } } }, guard);

    await wrapped.chat.completions.create({ model: "gpt-4o" });
    await wrapped.chat.completions.create({ model: "gpt-4o" });
    const blocked = await wrapped.chat.completions.create({ model: "gpt-4o" });

    expect(blocked.loopguardStatus.tripped).toBe(true);
    expect(calls).toBe(3);
    expect(guard.history).toHaveLength(0);
    expect(guard.signatures).toHaveLength(0);
    expect(guard.observedSignatures).toHaveLength(3);
  });

  test("observed request depth limit blocks distinct requests", () => {
    const guard = new CircuitBreaker({ policy: { maxDepth: 2, fallbackMode: "synthetic_response" } });
    expect(guard.observeToolRequest("first", {})).toBeNull();
    expect(guard.observeToolRequest("second", {})).toBeNull();
    const blocked = guard.observeToolRequest("third", {});

    expect(blocked.loopguardStatus.tripped).toBe(true);
    expect(guard.tripReason).toBe("max_depth_exceeded");
    expect(guard.observedSignatures).toHaveLength(3);
    expect(guard.signatures).toHaveLength(0);
    expect(guard.currentDepth).toBe(0);
  });

  test("wrapper stops provider after observed request depth trip", async () => {
    let calls = 0;
    const names = ["first", "second", "third"];
    const guard = new CircuitBreaker({ policy: { maxDepth: 2, fallbackMode: "synthetic_response" } });
    const wrapped = wrapOpenAI({ chat: { completions: { create: async () => {
      const name = names[calls++];
      return { choices: [{ message: { tool_calls: [{ function: { name, arguments: "{}" } }] } }] };
    } } } }, guard);

    await wrapped.chat.completions.create({ model: "gpt-4o" });
    await wrapped.chat.completions.create({ model: "gpt-4o" });
    expect((await wrapped.chat.completions.create({ model: "gpt-4o" })).loopguardStatus.tripped).toBe(true);
    expect((await wrapped.chat.completions.create({ model: "gpt-4o" })).loopguardStatus.tripped).toBe(true);

    expect(calls).toBe(3);
    expect(guard.observedSignatures).toHaveLength(3);
  });

  test("observed requests and actual execution use separate histories", () => {
    const guard = new CircuitBreaker({ policy: { maxConsecutiveRetries: 2 } });
    expect(guard.observeToolRequest("lookup", '{"id":1}')).toBeNull();
    expect(guard.beforeToolCall("lookup", { id: 1 })).toBeNull();
    guard.afterToolCall({ toolName: "lookup", args: { id: 1 }, result: "ok" });

    expect(guard.observedSignatures).toHaveLength(1);
    expect(guard.signatures).toHaveLength(1);
    expect(guard.state).toBe("closed");
  });

  test("wrapAnthropic blocks an alternating observed cycle", async () => {
    let calls = 0;
    const steps = [["a", { x: 1 }], ["b", { y: 2 }], ["a", { x: 1 }], ["b", { y: 2 }]] as const;
    const guard = new CircuitBreaker({ policy: { maxConsecutiveRetries: 5, maxCycleLength: 2, fallbackMode: "synthetic_response" } });
    const wrapped = wrapAnthropic({ messages: { create: async () => {
      const [name, input] = steps[calls++];
      return { content: [{ type: "tool_use", name, input }] };
    } } }, guard);

    await wrapped.messages.create({ model: "claude-3-5-sonnet" });
    await wrapped.messages.create({ model: "claude-3-5-sonnet" });
    await wrapped.messages.create({ model: "claude-3-5-sonnet" });
    const blocked = await wrapped.messages.create({ model: "claude-3-5-sonnet" });

    expect(blocked.loopguardStatus.tripped).toBe(true);
    expect(calls).toBe(4);
    expect(guard.history).toHaveLength(0);
  });

  test("wrappers do not call a provider after the guard trips", async () => {
    let calls = 0;
    const guard = new CircuitBreaker({ policy: { maxCostUsd: 0.01, fallbackMode: "synthetic_response" } });
    guard.recordUsage({ promptTokens: 10_000, completionTokens: 0, model: "gpt-4o" });
    const wrapped = wrapOpenAI({ chat: { completions: { create: async () => { calls++; throw new Error("must not call provider"); } } } }, guard);

    const blocked = await wrapped.chat.completions.create({ model: "gpt-4o" });

    expect(blocked.loopguardStatus.tripped).toBe(true);
    expect(calls).toBe(0);
  });

  test("wrappers reject streaming requests before calling the provider", async () => {
    let calls = 0;
    const wrapped = wrapOpenAI({ chat: { completions: { create: async () => { calls++; throw new Error("must not call provider"); } } } }, new CircuitBreaker());

    await expect(wrapped.chat.completions.create({ model: "gpt-4o", stream: true })).rejects.toThrow("streaming");
    expect(calls).toBe(0);
  });
});
