import { CircuitBreaker } from "../core";

export function wrapOpenAI<T extends Record<string, any>>(client: T, guard: CircuitBreaker): T {
  if (client.chat && client.chat.completions && typeof client.chat.completions.create === "function") {
    const originalCreate = client.chat.completions.create.bind(client.chat.completions);

    client.chat.completions.create = async function (...args: any[]) {
      const params = args[0] || {};
      const model = params.model || "gpt-4o";

      const response = await originalCreate(...args);

      if (response && response.usage) {
        guard.recordUsage({
          promptTokens: response.usage.prompt_tokens || 0,
          completionTokens: response.usage.completion_tokens || 0,
          model,
          cachedTokens: response.usage.prompt_tokens_details?.cached_tokens || 0,
        });
      }

      if (response && response.choices) {
        for (const choice of response.choices) {
          const toolCalls = choice.message?.tool_calls || [];
          for (const tc of toolCalls) {
            if (tc.function) {
              const toolName = tc.function.name || "unknown";
              const toolArgs = tc.function.arguments || "{}";
              const fallback = guard.beforeToolCall(toolName, toolArgs);
              if (fallback !== null && fallback !== undefined) {
                return fallback;
              }
            }
          }
        }
      }

      return response;
    };
  }

  return client;
}
