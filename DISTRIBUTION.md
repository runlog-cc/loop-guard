# Loop-Guard downloads and checksums

Free MIT-licensed packages; no account, hosted collector or subscription is
required. These POSIX/WSL commands run in a new working folder. Download the
artifact(s) you need and verify the matching entries before installation:

```sh
curl -fLO https://github.com/runlog-cc/loop-guard/releases/download/v0.3.1/runlog_loopguard-0.3.1-py3-none-any.whl
curl -fLO https://github.com/runlog-cc/loop-guard/releases/download/v0.3.1/runlog-loopguard-0.3.1.tgz
curl -fLO https://github.com/runlog-cc/loop-guard/releases/download/v0.3.1/SHA256SUMS
awk '$2 == "runlog_loopguard-0.3.1-py3-none-any.whl" || $2 == "runlog-loopguard-0.3.1.tgz" {print; count++} END {if (count != 2) exit 1}' SHA256SUMS > guard.SHA256SUMS
sha256sum --check guard.SHA256SUMS
```

On macOS use `shasum -a 256 -c guard.SHA256SUMS`. On native PowerShell compare
`Get-FileHash -Algorithm SHA256` for each file with its exact manifest entry;
the `awk` command above requires a POSIX shell or WSL. Checksums verify integrity,
not independent authorship.

For Python:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ./runlog_loopguard-0.3.1-py3-none-any.whl
```

For a Node project, from that project's directory after downloading the tarball:

```sh
npm install ./runlog-loopguard-0.3.1.tgz
```

Do not assume registry package names exist. The GitHub release downloads are the
supported installation method. Wheel/npm installs contain package code, not the
full repository examples or tests. For those, clone the repository and follow
[the root guide](README.md). See [Python](packages/python/README.md) and
[TypeScript](packages/typescript/README.md) for direct API examples.

These default-branch docs do not replace or modify the immutable v0.3.1 artifacts.
