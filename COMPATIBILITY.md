# Loop-Guard 0.3.0 compatibility evidence

These are local controlled-transport tests of real pinned SDKs, not live-provider certification. No provider accounts or paid requests are used. The SDKs serialize requests and parse fixture HTTP responses. Versions outside this matrix are unverified.

| Runtime | OpenAI SDK | Anthropic SDK | Verified surface |
| --- | --- | --- | --- |
| Python 3.12.3 | `openai==1.84.0` | `anthropic==0.52.2` | synchronous non-streaming Chat Completions / Messages |
| Node.js 24.15.0 | `openai@4.104.0` | `@anthropic-ai/sdk@0.54.0` | asynchronous non-streaming Chat Completions / Messages |

Both suites cover text-only replies, tool requests, custom null/undefined fallback, optional null cached-token fields, cache reads, provider errors, missing usage and finite attempt admission. Anthropic cache creation is explicitly rejected and halts the guard after the response: its billing is unsupported. OpenAI cache-write billing is not claimed. Unknown models fail pricing lookup before dispatch. Missing usage and errors increase `unaccounted_provider_attempts` / `unaccountedProviderAttempts`; reported spend is then only a partial estimate, never a certified zero-cost request.

Set SDK `max_retries=0` (Python) / `maxRetries: 0` (Node) when a cap on HTTP attempts is required. `max_provider_attempts` / `maxProviderAttempts` defaults to 100 and counts each admitted wrapper dispatch, including tool-less responses and failed calls. Internal SDK retries are invisible and are not individually counted. The guard blocks dispatch N+1. Reset preserves attempt consumption; create a new session deliberately to start a fresh allowance. Tool depth and estimated cost ceilings remain independent.

`loop_exempt_tools=['poll_job']` / `loopExemptTools: ['poll_job']` excludes exact tool names from repeat/cycle detection only. Exempt calls still consume observed/executed depth, dispatch attempts and reported usage. Nonexempt signatures retain their own repeat/cycle checks after filtering exempt signatures. Use a higher depth limit for deliberate polling, with finite attempt and budget ceilings.

Unsupported: Python async clients, streaming, OpenAI Responses API, SDK streaming helpers, overlapping requests per guard, unwrapped/beta/batch/provider surfaces, and Anthropic cache creation accounting. Python wrappers reject async and both wrappers reject supported-entry streaming before dispatch. The wrappers replace `create`; Node SDK-specific return helpers such as `.withResponse()` / `.asResponse()` are not preserved. Applications must call explicit before/after lifecycle hooks around actual tool execution; observing a provider tool request does not execute it.

Run the evidence locally:

```sh
python -m pip install -r packages/python/tests/requirements-sdk.txt
PYTHONPATH=packages/python python -m pytest packages/python/tests
npm --prefix packages/typescript ci
npm --prefix packages/typescript run build
node --test packages/typescript/tests/*.cjs
bun test packages/typescript/tests/circuit_breaker.test.ts
```

`examples/metadata_incident_exporter.py` is opt-in: it requires an explicit HTTPS endpoint and bearer token, sends no data on import, rejects redirects and exports a scalar allowlist without prompts, outputs, arguments, signatures or session identifiers. Collector failures are swallowed by the existing callback boundary; this example is not durable delivery or a hosted collector.
