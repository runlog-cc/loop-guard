# Loop-Guard

Free Python and TypeScript SDKs for detecting repeated agent tool requests and
checking returned usage. A **sequential session circuit breaker**, not a provider
proxy or a hard dollar cap. Part of the [RunLog public toolkit](https://runlog.cc/loop-guard/),
built and maintained by **Vasco Lacerda**.

[About the developer](https://runlog.cc/about) · [Discuss a role or project](mailto:hello@runlog.cc?subject=Role%20or%20project%20discussion)

[Offline verification workflow and runs](https://github.com/runlog-cc/loop-guard/actions/workflows/verify.yml)

## Run a local example

From a POSIX shell (macOS, Linux or Windows WSL) with Git and Python 3.9+:

```sh
git clone https://github.com/runlog-cc/loop-guard.git
cd loop-guard
PYTHONPATH=packages/python python3 examples/fake_provider.py
```

Expected: the fake provider/tool loop stops after repeated requests and prints
fixture usage. It contacts no provider and needs no account or key. Commands in
this README run from the repository root; a package installed from a wheel does
not contain the repository's examples or tests.

## What to inspect

| Engineering decision | Implementation and evidence |
| --- | --- |
| Bounded repeats, cycles, depth and provider attempts | [Python core](packages/python/loopguard/core.py), [TypeScript API](packages/typescript/src/index.ts), [core tests](packages/python/tests/test_circuit_breaker.py) |
| Real SDK parsing without live provider traffic | [Python transport tests](packages/python/tests/test_sdk_integration.py), [Node SDK tests](packages/typescript/tests/sdk-integration.cjs) |
| Returned usage is different from a guaranteed invoice | [Budget accounting](packages/python/loopguard/budget.py), [regressions](packages/python/tests/test_audit_regressions.py) |
| Supported modes are explicit | [Compatibility matrix and failure boundaries](COMPATIBILITY.md) |

I use AI in implementation and review, with local fixtures and pinned SDK tests
to check behavior. Passing these tests is not certification of every SDK version
or workload.

## Install released packages

Use the [immutable v0.3.1 downloads](https://github.com/runlog-cc/loop-guard/releases/tag/v0.3.1).
Choose the Python wheel or Node tarball you need; neither is a hosted subscription.
The [download and checksum guide](DISTRIBUTION.md) covers installation.
[Python usage](packages/python/README.md) · [TypeScript usage](packages/typescript/README.md).

## Supported modes and limits

- Python synchronous / Node Promise nonstreaming OpenAI Chat Completions and
  Anthropic Messages wrappers. Responses API, Python async, streaming, SDK helper
  return methods and overlapping requests per guard are unsupported. See the
  exact [pinned compatibility matrix](COMPATIBILITY.md).
- Budgets use **returned provider usage**. One request can exceed the remaining
  budget before returning. There is no reservation, cancellation, shared ledger
  or guaranteed hard spending cap. Missing/invalid usage is not verified zero cost.
- Exact model IDs and bundled historical reference prices are used. Unknown
  models fail before dispatch; configure an exact price or explicit manual cost.
  Anthropic cache creation billing is unsupported. Reference estimates are not
  provider invoices.
- Disable SDK internal retries (`max_retries=0` / `maxRetries: 0`) if an admitted
  wrapper-attempt ceiling must also limit HTTP attempts. Reset does not replenish
  attempts or spend. Poll exemptions still consume attempts, depth and usage.
- Call the explicit before/after hooks around real tool execution. Observing a
  model's tool request does not execute that tool. Synthetic fallbacks are plain
  application objects, not provider SDK response classes.
- Telemetry callbacks can receive raw application data; redact it before sending
  elsewhere. The optional [metadata exporter](examples/metadata_incident_exporter.py)
  sends a scalar allowlist only to a compatible HTTPS collector **you configure**.
  No hosted collector, Teams plan or incident-history service is offered here.

## Verify from this checkout

Use a POSIX/WSL shell, Python 3.12 and Node.js 22 for these tested development
commands. First create
an isolated environment, then install the pinned test-only SDKs:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r packages/python/tests/requirements-sdk.txt
PYTHONPATH=packages/python .venv/bin/python -m pytest packages/python/tests
npm --prefix packages/typescript ci --ignore-scripts
npm --prefix packages/typescript run test:node
```

The SDKs parse fixtures over controlled local transports; no real provider key or
model call is used. Python 3.9+ / Node.js 20+ are the declared package floors; the
CI development matrix above does not establish every runtime/version combination.
For the additional native TypeScript suite, run
`bun test packages/typescript/tests/circuit_breaker.test.ts` with Bun 1.3.12.
Bun is optional for the Node integration suite. The public export has no local
server/dashboard package; use the [browser demonstration](https://runlog.cc/loop-guard/)
for a simulation, or the SDK for real application checks.

## Documentation and released versions

These default-branch docs describe the existing **0.3.1** runtime. Published
`v0.3.1` tags, downloads and checksums remain unchanged; this documentation update
is not a new package release. `RELEASE.json` describes historical export context,
not the current public branch commit. For a CI source pin, review the public tag
and resolve it with `git rev-parse 'v0.3.1^{commit}'`; do not use an export hash as
though it were a public repository commit.

## Free use and license

MIT-licensed source and packages, including commercial use with the required
notice. See [LICENSE](LICENSE). Local guarding needs no RunLog account. Private
accounts, payments and hosted integrations remain outside the public toolkit.
