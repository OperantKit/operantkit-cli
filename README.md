# operantkit-cli

:jp: [日本語版 README](README.ja.md)

End-to-end command-line entry point for OperantKit sessions.

`operantkit-cli` wires together the OperantKit experiment stack:

```
contingency-dsl-py  →  parse DSL string
contingency-py      →  bridge AST → runtime Schedule
session-runner      →  drive Session
experiment-io       →  poll virtual / serial / HIL hardware
session-recorder    →  persist events to an OKL v1 log
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

## 30-second example

Run a fixed-interval 30-s schedule against the built-in virtual subject until 5 reinforcers are delivered:

```bash
operant run --schedule "FI30s" --output fi30.okl --exit-reinforcers 5
grep -v '^#' fi30.okl | cut -f2 | sort | uniq -c
#    5 reinforcer_end
#    5 reinforcer_start
#  132 response
#   12 state_change
tail -n 1 fi30.okl
# 154.56400194973696	state_change	RUNNING	FINISHED
```

Session time is simulated, so the 155-s session above finishes in about 0.1 s of wall time, and the log is identical on every run (the virtual subject is seeded with `--seed`, default `0`). `fi30.okl` starts with a header that records the DSL source and the column layout of every event type:

```
# OKL v1
# session_name = "session"
# clock_type = "ManualClock"
# session_start = 0.0
# meta:
#   dsl = "FI30s"
# events:
#   response          : id:int operandum:int?
#   reinforcer_start  : id:int potency:float operandum:int?
...
# ---
0.0	state_change	IDLE	RUNNING
1.8606071110652234	response	1	-
```

Analyze the log with [session-analyzer](https://github.com/OperantKit/session-analyzer) (`pip install session-analyzer`).

## Why not a 50-line hand-written session loop?

A short script that draws responses and checks a schedule usually leaves out the parts that make a session reportable:

- **One schedule notation for every procedure.** `--schedule` takes any [contingency-dsl](https://github.com/OperantKit/contingency-dsl) expression that [contingency-py](https://github.com/OperantKit/contingency-py) compiles, including concurrent and other compound schedules and program annotations such as `@algorithm("fleshler-hoffman", n=12, seed=42)`. VI / VR / VT values come from the Fleshler-Hoffman (1962) progression, not ad-hoc random draws.
- **One operandum per concurrent component.** For `Conc(...)` each component gets its own virtual operandum with an independent Poisson responder (seeds `--seed`, `--seed + 1`, ...), so every component is exposed to responding.
- **Reproducible runs.** With `@algorithm(..., seed=N)` in the DSL and a fixed `--seed`, two runs write byte-identical logs.
- **A self-describing log.** The OKL v1 header stores the session name, clock type, the DSL source, and the column layout of each event type (`response`, `reinforcer_start`, `reinforcer_end`, `state_change`, `component_change`, `phase_enter`, `phase_exit`).
- **Input errors stop before the session starts.** An invalid schedule or exit condition prints one `operant: error: ...` line, exits with status 2, and writes no log file.

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
| `--output PATH` | required | OKL v1 log output path. |
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
