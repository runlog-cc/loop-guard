# Loop-Guard for Node.js and TypeScript

Free MIT-licensed local circuit-breaker SDK. [Project, source tests and limits](../../README.md)
· [Download/checksum instructions](../../DISTRIBUTION.md).

## Use an installed package

Install the reviewed npm tarball in your Node.js 20+ project. It includes compiled
CommonJS JavaScript and TypeScript declarations; consumers do not need a build:

```js
const { CircuitBreaker } = require("@runlog/loopguard");
const guard = new CircuitBreaker();
guard.beforeToolCall("lookup", { id: 1 });
const result = { found: false };
guard.afterToolCall({ toolName: "lookup", args: { id: 1 }, result, costUsd: 0.001 });
```

The cost above is illustrative, not measured provider usage. This example makes
no network request. Configure and test a policy around actual tool execution.

## Build and verify from source

From the **repository root**, with Node.js 22 and npm:

```sh
npm --prefix packages/typescript ci --ignore-scripts
npm --prefix packages/typescript run test:node
```

That command compiles the SDK and runs Node core/real-SDK fixture regressions.
The additional native TypeScript suite uses Bun 1.3.12:

```sh
bun test packages/typescript/tests/circuit_breaker.test.ts
```

The public export has no local server/dashboard. The [compatibility matrix](../../COMPATIBILITY.md)
lists sequential nonstreaming wrappers and unsupported streaming/Responses/helper
APIs. Returned-usage budgets can overshoot on an in-flight request and are not
hard dollar caps. No hosted collector or RunLog account is required.
[MIT License](LICENSE).
