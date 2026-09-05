import { CircuitBreaker, TripPolicy } from "../packages/typescript/src/index";

console.log("\n=======================================================");
console.log("🤖 Launching TypeScript Agent with Loop-Guard Protection");
console.log("=======================================================\n");

const guard = new CircuitBreaker({
  sessionId: "ts_agent_web_search_loop",
  policy: {
    maxConsecutiveRetries: 3,
    maxCostUsd: 2.0,
    fallbackMode: "synthetic_response",
    fallbackMessage: "Loop-Guard: Web search endpoint failing. Halted retries.",
  },
  onTrip: (cb, details) => {
    console.log(`\n🚨 [ALERT] Circuit Breaker Tripped!`);
    console.log(`   Session ID: ${cb.sessionId}`);
    console.log(`   Reason:     ${details.reason}`);
    console.log(`   Tool:       ${details.toolName}`);
    console.log(`   Cost:       $${cb.budget.totalCostUsd.toFixed(4)}`);
  },
});

const queryArgs = { query: "OpenAI latest pricing model 2026", limit: 5 };

for (let step = 1; step <= 5; step++) {
  console.log(`--- [Step ${step}] Agent attempts search tool ---`);

  // Record mock token usage
  guard.recordUsage({
    promptTokens: 2500,
    completionTokens: 80,
    model: "claude-3-5-sonnet",
  });

  const fallback = guard.beforeToolCall("web_search", queryArgs);
  if (fallback) {
    console.log(`🛑 [CIRCUIT OPEN] Tool call blocked by Loop-Guard!`);
    console.log(`   Fallback response: "${fallback.content}"`);
    console.log(`   Total spent: $${guard.budget.totalCostUsd.toFixed(4)}`);
    break;
  }

  console.log(`   Tool returned: Error 503 Service Unavailable`);
  guard.afterToolCall({
    toolName: "web_search",
    args: queryArgs,
    result: "503 Service Unavailable",
    isError: true,
  });
}

console.log("\n✅ TypeScript simulation complete.\n");
