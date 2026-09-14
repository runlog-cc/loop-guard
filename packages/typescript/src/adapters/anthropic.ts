import { CircuitBreaker } from "../core";
import { getPricingForModel } from "../budget";

export function wrapAnthropic<T extends Record<string, any>>(client: T, guard: CircuitBreaker): T {
  if (client.messages && typeof client.messages.create === "function") {
    const originalCreate = client.messages.create.bind(client.messages);

    client.messages.create = async function (...args: any[]) {
      if (args[0]?.stream === true) {
        throw new Error("Loop-Guard does not support streaming Anthropic responses; use explicit lifecycle calls.");
      }
      guard.beginRequest();
      let responseReceived = false;
      try {
      const blocked = guard.ensureActive();
      if (guard.state === "tripped") return blocked;
      const params = args[0] || {};
      const model = params.model || "claude-3-5-sonnet";

      getPricingForModel(model);
      const response = await originalCreate(...args);
      responseReceived = true;

      if (response?.usage?.cache_creation_input_tokens) throw new Error("Cache creation billing unsupported; use explicit normalized usage");
      if (response && response.usage) {
        guard.recordUsage({
          promptTokens: (response.usage.input_tokens ?? 0) + (response.usage.cache_read_input_tokens ?? 0),
          completionTokens: response.usage.output_tokens ?? 0,
          model,
          cachedTokens: response.usage.cache_read_input_tokens ?? 0,
        });
      }

      if (response && response.content) {
        for (const block of response.content) {
          if (block.type === "tool_use") {
            const toolName = block.name || "unknown";
            const toolInput = block.input || {};
            const fallback = guard.observeToolRequest(toolName, toolInput);
            if (fallback !== null && fallback !== undefined) {
              return fallback;
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
  if (client.messages?.stream) client.messages.stream = unsupported;
  return client;
}
