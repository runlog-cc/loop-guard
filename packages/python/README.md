# RunLog LoopGuard Python 0.1.0

Local circuit breaker SDK for tool repetition, cycles, depth and budget limits.
Python 3.9+. No required runtime dependencies. Optional adapters may require their
provider SDKs. Budget prices are bundled estimates: supply current model prices
and usage to enforce appropriate limits. This package does not provision hosted
telemetry, tenant authentication, subscriptions or service guarantees.

```sh
python -m pip install ./runlog_loopguard-0.1.0-py3-none-any.whl
```

```python
from loopguard import CircuitBreaker, TripPolicy
breaker = CircuitBreaker(policy=TripPolicy(max_consecutive_retries=3))
```

See source tests for complete call/exception examples. Tests: `python -m pytest tests`.
