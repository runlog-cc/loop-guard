# Loop-Guard for Python

Free MIT-licensed local circuit-breaker SDK. [Project, source tests and limits](../../README.md)
· [Download/checksum instructions](../../DISTRIBUTION.md).

## Use an installed package

Install the reviewed Python wheel with Python 3.9+, then use the hooks around your
actual tool execution:

```python
from loopguard import CircuitBreaker

guard = CircuitBreaker()
guard.before_tool_call("lookup", {"id": 1})
result = {"found": False}
guard.after_tool_call("lookup", {"id": 1}, result=result, cost_usd=0.001)
```

The cost above is an illustrative explicit value, not measured provider usage.
The example makes no network request. A tripped guard raises unless you configure
a supported fallback. Use the actual provider cost in your own application.

## Run repository examples/tests

These POSIX/WSL commands run from a **source checkout's root**, not an installed wheel:

```sh
PYTHONPATH=packages/python python3 examples/fake_provider.py
python3 -m venv .venv
.venv/bin/python -m pip install -r packages/python/tests/requirements-sdk.txt
PYTHONPATH=packages/python .venv/bin/python -m pytest packages/python/tests
```

Tests use controlled transports with pinned SDKs, not paid model calls. There is
no server/dashboard in this public source export. See [COMPATIBILITY](../../COMPATIBILITY.md)
for sequential/nonstreaming supported clients and unsupported modes. Budgets are
checked after responses and cannot guarantee a hard dollar cap. Unknown/missing
usage must not be represented as verified zero cost. No RunLog account or hosted
collector is required. [MIT License](LICENSE).
