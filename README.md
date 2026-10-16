# operantkit-cli

:jp: [日本語版 README](README.ja.md)

End-to-end command-line entry point for OperantKit sessions.

`operantkit-cli` wires together the OperantKit experiment stack:

```
contingency-dsl-py  →  parse DSL string
contingency-py      →  bridge AST → runtime Schedule
session-runner      →  drive Session
experiment-io       →  poll virtual / serial / HIL hardware
session-recorder    →  persist events to JSONL
```

## Installation

```bash
pip install operantkit-cli
```

This installs the `operant` command together with the six OperantKit
libraries it drives (contingency-dsl-py, contingency-py, experiment-core,
session-runner, session-recorder, experiment-io).

### Development

```bash
mise exec -- python -m venv .venv
mise exec -- .venv/bin/python -m pip install -e '.[dev]'
```

If the sibling OperantKit libraries are not yet available from your
package index, build or download their wheels into one directory and
point pip at it:

```bash
mise exec -- .venv/bin/python -m pip install --find-links <wheel-dir> -e '.[dev]'
```

## Usage

```bash
operant run --schedule "FR3" \
    --output fr3.okl \
    --exit-reinforcers 5 \
    --virtual-rate-hz 5.0
```

`--schedule` accepts any expression supported by `contingency_dsl.parse`
+ `contingency.bridge.from_dsl` (e.g. `"FI30s"`,
`"Conc(VI30s, VI60s)"`). Use `--exit-reinforcers N` or
`--exit-time SECONDS` (mutually exclusive). Equivalent invocation via
the module: `python -m operantkit_cli run ...`.

Program-level annotations are accepted. To make VI / VR / VT sessions
reproducible, seed the schedule values in the DSL itself:

```bash
operant run --schedule $'@algorithm("fleshler-hoffman", n=12, seed=42)\nConc(VI30s, VI60s)' \
    --output conc.okl --exit-time 1800 --seed 0
```

The components receive seeds 42, 43, ... in source order. `--seed` seeds
only the virtual subject's responding. VI / VR / VT values are generated
by Fleshler-Hoffman only; `@algorithm("arithmetic")` is rejected with an error.

## Subcommands

### `run`

Run a session against a virtual Poisson subject and write an OKL v1 log.

| Flag | Default | Meaning |
|---|---|---|
| `--schedule DSL` | required | contingency-dsl source. |
| `--output PATH` | required | JSONL output path. |
| `--exit-reinforcers N` | (one of these required) | Stop after N reinforcers. |
| `--exit-time SECONDS` |  | Stop after SECONDS of session time. |
| `--name NAME` | `session` | Session label. |
| `--virtual-rate-hz HZ` | `1.0` | Virtual subject Poisson rate. |
| `--seed N` | `0` | Subject RNG seed. |
| `--reinforcer-duration SEC` | `0.5` | Per-delivery hold time. |
| `--poll-interval SEC` | `0.001` | Idle clock advance per iteration. |
| `--max-steps N` | `5000` | Loop iteration cap. |
| `--max-duration SEC` | none | Optional wall-time ceiling. |

## Development

```bash
.venv/bin/pytest
.venv/bin/pytest --cov=src --cov-report=term-missing
.venv/bin/ruff check src tests
.venv/bin/black --check src tests
```

## Deferred features

- `--config FILE.yaml` — declarative session-spec loader (waits on a
  separate `schedule-dsl` package for full session specs).
- `--backend {serial,hil}` — currently only the virtual backend is
  exposed; `experiment-io` already supports the others.
- Snapshot tests against deterministic real schedules.
