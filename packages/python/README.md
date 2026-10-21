# Loop-Guard 0.3.1

A sequential session circuit breaker for repeated tool requests, cycles, attempted-call limits, and **post-response** usage budgets. Free source SDK; the local dashboard is a demo, not a provider proxy or hosted enforcement service.

## License

Loop-Guard is free to use and is licensed under the MIT License. You may use, copy, modify, and redistribute it, including commercially, provided you retain the copyright and license notice. The full license is included in this Python package download. Hosted RunLog services have separate terms.

## Supported modes

| Entry point | Python | TypeScript |
| --- | --- | --- |
| OpenAI `chat.completions.create` | synchronous, non-streaming | Promise, non-streaming |
| Anthropic `messages.create` | synchronous, non-streaming | Promise, non-streaming |
| Manual tool lifecycle | sequential before/after pairs | sequential before/after pairs |
| Python async clients / streaming | rejected | streaming rejected |
| Responses API, streaming helper APIs, LangChain/LangGraph enforcement | unsupported; do not route protected work through these APIs | unsupported |

Each guard admits one model request at a time; overlaps throw before provider dispatch. Manual tools require a matching before/after pair; overlapping calls and unmatched completions throw. Use separate guards for separate sessions. `max_depth`/`maxDepth` counts attempted calls, not recursive stack depth. Adapters observe requested tools independently from actual execution. Use `loop_exempt_tools` / `loopExemptTools` for deliberate polling; exemptions bypass repetition detection only.

Budgets use returned provider usage: a request can exceed the remaining budget before it returns. There is no reservation, cancellation, shared ledger, or hard dollar cap. Subsequent wrapped requests are blocked, including tool-less calls. Missing provider usage cannot be charged automatically. Manual tool costs are additional costs; do not record the same provider cost twice. Reset preserves spend and refuses exhausted budgets or in-flight work; create a new session for a new budget.

Pricing is a bundled historical reference, not a live price feed. Matching is exact, including explicitly listed dated IDs. Unknown models raise before dispatch; register an exact `MODEL_CATALOG` price or use manual normalized usage with explicit cost. Tokens must be finite nonnegative integers; costs/prices must be finite and nonnegative. Cached tokens are included within total prompt tokens. Anthropic cache reads are normalized; cache creation billing is unsupported and raises, so use uncached requests or manual explicit billing for caching workflows.

Synthetic/custom fallbacks are plain application objects, not provider SDK response classes. Prefer exception mode unless the calling application handles these values explicitly. Provider helpers and endpoints outside the table are not protected merely because the client was wrapped.

## Offline example

Install the Python package, then run `python examples/fake_provider.py` from the source checkout. It executes a complete fake OpenAI adapter/tool loop, records returned usage, and stops the third identical request without contacting any service.

```python
from loopguard import CircuitBreaker

guard = CircuitBreaker()
guard.before_tool_call("lookup", {"id": 1})
result = {"found": False}
guard.after_tool_call("lookup", {"id": 1}, result=result, cost_usd=0.001)
```

```typescript
import { CircuitBreaker } from "@runlog/loopguard";
const guard = new CircuitBreaker();
guard.beforeToolCall("lookup", { id: 1 });
guard.afterToolCall({ toolName: "lookup", args: { id: 1 }, result: "empty", costUsd: 0.001 });
```

## Local demo dashboard

`python server/app.py` binds loopback only. Requests require a localhost/127.0.0.1 Host and same Origin when supplied; wildcard CORS is removed. Optional `LOOPGUARD_TOKEN` requires `Authorization: Bearer ...` on all requests (use an authenticated local client; browser EventSource cannot supply that header). Without a token, the demo trusts local processes. Do not expose it through a public reverse proxy.

Static paths are contained in the static directory. Ingestion is limited to 64 KiB, retention to 100 sessions, SSE to 16 clients, connection threads to 32, and simulations to two concurrently. Raw arguments/results and common secret fields are redacted on ingestion. SDK telemetry callbacks still receive raw application data: redact it before sending to other destinations. These bounds do not make the demo a multi-tenant service.

## Verification

`PYTHONPATH=packages/python pytest packages/python/tests server/tests`

`cd packages/typescript && npm ci && npm run build && node --test tests/audit.cjs`

All examples and regression checks use local controlled providers; no provider account or paid call is needed.

## 0.3.1 dispatch limits and compatibility

`TripPolicy(max_provider_attempts=100, loop_exempt_tools=["poll_job"])` / `{ maxProviderAttempts: 100, loopExemptTools: ["poll_job"] }` caps admitted wrapper calls, including tool-less replies and errors. Dispatch N+1 is blocked; reset does not replenish attempts. Disable SDK internal retries (`max_retries=0` / `maxRetries: 0`) to make this also an HTTP-attempt cap. Exempt tools still consume depth, attempts and reported budget; other signatures retain repetition checks.

Telemetry reports `unaccounted_provider_attempts` / `unaccountedProviderAttempts` for errors and missing/invalid usage. Spend is only a partial estimate when this is nonzero. A custom `None` / `undefined` fallback suppresses the response that caused the trip as well as later calls.

Local real-SDK compatibility tests pin Python `openai==1.84.0`, `anthropic==0.52.2`, `httpx==0.28.1`, and Node `openai@4.104.0`, `@anthropic-ai/sdk@0.54.0`. Tested on Python 3.12.3 and Node 24.15.0; native source tests use Bun 1.3.12. Other SDK versions are unverified. Tested modes are synchronous Python / Promise Node, non-streaming Chat Completions and Messages. Anthropic cache creation, streaming, Python async, Responses API and Node SDK response helpers remain unsupported.

The source checkout includes `COMPATIBILITY.md`, pinned SDK test commands, and the opt-in `examples/metadata_incident_exporter.py` allowlist example. It needs an explicit HTTPS endpoint/token and exports no prompts, outputs, arguments, signatures or session identifiers. There is no hosted collector in this release.
