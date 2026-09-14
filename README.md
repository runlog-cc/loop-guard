# RunLog Loop-Guard

Python and TypeScript circuit-breaker SDKs for local agent integrations. This release contains source, tests, and an opt-in metadata exporter for RunLog Teams or your compatible collector.

Download the wheel or npm tarball from [releases](https://github.com/runlog-cc/loop-guard/releases). Check SHA256SUMS before installing:

```sh
curl -fLO https://github.com/runlog-cc/loop-guard/releases/download/v0.3.0/runlog_loopguard-0.3.0-py3-none-any.whl
curl -fLO https://github.com/runlog-cc/loop-guard/releases/download/v0.3.0/runlog-loopguard-0.3.0.tgz
curl -fLO https://github.com/runlog-cc/loop-guard/releases/download/v0.3.0/SHA256SUMS
awk '$2 == "runlog_loopguard-0.3.0-py3-none-any.whl" || $2 == "runlog-loopguard-0.3.0.tgz" {print; count++} END {if (count != 2) exit 1}' SHA256SUMS > guard.SHA256SUMS
sha256sum --check guard.SHA256SUMS
pip install ./runlog_loopguard-0.3.0-py3-none-any.whl
npm install ./runlog-loopguard-0.3.0.tgz
```

See [Python](packages/python/README.md) and [TypeScript](packages/typescript/README.md) for integration examples. Configure retry and budget thresholds and test on your own traces before production use. Budget checks depend on observed usage; they cannot guarantee prevention of every upstream charge.

## 0.3.0 dispatch limits and compatibility

`TripPolicy(max_provider_attempts=100, loop_exempt_tools=["poll_job"])` / `{ maxProviderAttempts: 100, loopExemptTools: ["poll_job"] }` caps admitted wrapper calls, including tool-less replies and errors. Dispatch N+1 is blocked; reset does not replenish attempts. Disable SDK internal retries (`max_retries=0` / `maxRetries: 0`) to make this also an HTTP-attempt cap. Exempt tools still consume depth, attempts and reported budget; other signatures retain repetition checks.

Telemetry reports `unaccounted_provider_attempts` / `unaccountedProviderAttempts` for errors and missing/invalid usage. Spend is only a partial estimate when this is nonzero. A custom `None` / `undefined` fallback suppresses the response that caused the trip as well as later calls.

Local real-SDK compatibility tests pin Python `openai==1.84.0`, `anthropic==0.52.2`, `httpx==0.28.1`, and Node `openai@4.104.0`, `@anthropic-ai/sdk@0.54.0`. Tested on Python 3.12.3 and Node 24.15.0; native source tests use Bun 1.3.12. Other SDK versions are unverified. Tested modes are synchronous Python / Promise Node, non-streaming Chat Completions and Messages. Anthropic cache creation, streaming, Python async, Responses API and Node SDK response helpers remain unsupported.

The source checkout includes `COMPATIBILITY.md`, pinned SDK test commands, and the opt-in `examples/metadata_incident_exporter.py` allowlist example. It needs an explicit HTTPS endpoint/token and exports no prompts, outputs, arguments, signatures or session identifiers. The optional RunLog collector is `https://runlog.cc/api/teams/ingest`; create a write-scoped key at https://runlog.cc/developers/teams/. Local guarding works without an account. The exporter sends no measured cost when only reference-price estimates are available.
