# RunLog Loop-Guard

Python and TypeScript circuit-breaker SDKs for local agent integrations. This release contains source and tests; hosted telemetry is not included.

Download the wheel or npm tarball from [releases](https://github.com/runlog-cc/loop-guard/releases). Check SHA256SUMS before installing:

```sh
pip install ./runlog_loopguard-0.2.0-py3-none-any.whl
npm install ./runlog-loopguard-0.2.0.tgz
```

See [Python](packages/python/README.md) and [TypeScript](packages/typescript/README.md) for integration examples. Configure retry and budget thresholds and test on your own traces before production use. Budget checks depend on observed usage; they cannot guarantee prevention of every upstream charge.
