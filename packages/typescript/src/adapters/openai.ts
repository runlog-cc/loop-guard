import { CircuitBreaker } from "../core";
import { getPricingForModel } from "../budget";

export function wrapOpenAI<T extends Record<string, any>>(client: T, guard: CircuitBreaker): T {
  if (client.chat && client.chat.completions && typeof client.chat.completions.create === "function") {
    const originalCreate = client.chat.completions.create.bind(client.chat.completions);

    client.chat.completions.create = async function (...args: any[]) {
      if (args[0]?.stream === true) {
        throw new Error("Loop-Guard does not support streaming OpenAI responses; use explicit lifecycle calls.");
      }
      guard.beginRequest();
      let responseReceived = false;
      try {
      const blocked = guard.ensureActive();
      if (guard.state === "tripped") return blocked;
      const params = args[0] || {};
      const model = params.model || "gpt-4o";

      getPricingForModel(model);
      const response = await originalCreate(...args);
      responseReceived = true;

      if (response && response.usage) {
        guard.recordUsage({
          promptTokens: response.usage.prompt_tokens ?? 0,
          completionTokens: response.usage.completion_tokens ?? 0,
          model,
          cachedTokens: response.usage.prompt_tokens_details?.cached_tokens ?? 0,
        });
      }

      if (response && response.choices) {
        for (const choice of response.choices) {
          const toolCalls = choice.message?.tool_calls || [];
          for (const tc of toolCalls) {
            if (tc.function) {
              const toolName = tc.function.name || "unknown";
              const toolArgs = tc.function.arguments || "{}";
              // This is a provider-requested tool only. The application owns
              // the explicit beforeToolCall/afterToolCall execution lifecycle.
              const fallback = guard.observeToolRequest(toolName, toolArgs);
              if (fallback !== null && fallback !== undefined) {
                return fallback;
              }
            }
          }
        }
      }

      return response;
      } catch (error) {
        if (responseReceived) guard.haltOnAccountingFailure();
        throw error;
      } finally { guard.endRequest(); }
    };
  }

  const unsupported = () => { throw new Error("Loop-Guard does not support this API or streaming helper"); };
  if (client.responses) client.responses.create = unsupported;
  if (client.chat?.completions?.stream) client.chat.completions.stream = unsupported;
  return client;
}
