import { CircuitBreaker } from "../core";

export function wrapAnthropic<T extends Record<string, any>>(client: T, guard: CircuitBreaker): T {
  if (client.messages && typeof client.messages.create === "function") {
    const originalCreate = client.messages.create.bind(client.messages);

    client.messages.create = async function (...args: any[]) {
      const params = args[0] || {};
      const model = params.model || "claude-3-5-sonnet";

      const response = await originalCreate(...args);

      if (response && response.usage) {
        guard.recordUsage({
          promptTokens: response.usage.input_tokens || 0,
          completionTokens: response.usage.output_tokens || 0,
          model,
          cachedTokens: response.usage.cache_read_input_tokens || 0,
        });
      }

      if (response && response.content) {
        for (const block of response.content) {
          if (block.type === "tool_use") {
            const toolName = block.name || "unknown";
            const toolInput = block.input || {};
            const fallback = guard.beforeToolCall(toolName, toolInput);
            if (fallback !== null && fallback !== undefined) {
              return fallback;
            }
          }
        }
      }

      return response;
    };
  }

  return client;
}
