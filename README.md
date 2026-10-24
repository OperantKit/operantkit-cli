# operantkit-cli

:jp: [日本語版 README](README.ja.md)

`operant run` runs one session of a reinforcement schedule against a simulated subject and writes every event to a plain-text log, without writing any code. It is the command-line entry point of [OperantKit](https://github.com/OperantKit): it parses the schedule with contingency-dsl-py, runs it with contingency-py, experiment-core, session-runner, and experiment-io, and writes the log with session-recorder.

- **One expression in, one log out.** `--schedule "Conc(VI30s, VI60s, COD=2s)"` is the whole procedure.
- **Seconds, not hours.** Session time is simulated, and the same seeds write the same log byte for byte.
- **Mistakes stop before the session.** An invalid schedule prints one error line and writes no log.

Use it to see what a schedule program actually delivers before an animal runs on it, to make example data for teaching, or to feed an analysis pipeline with a log of known content.

## Installation

Python 3.11 or newer. The packages are not on PyPI yet, so install them from GitHub without dependency resolution:

```bash
G=git+https://github.com/OperantKit
pip install --no-deps $G/contingency-dsl-py $G/contingency-py $G/experiment-core \
  $G/session-runner $G/session-recorder $G/experiment-io $G/operantkit-cli
```

No third-party library is needed. `pip check` reports version mismatches between these development builds; they do not affect the command.

## 30-second example

Run a fixed-interval (FI) 30-s schedule against the built-in virtual subject until 5 reinforcers are delivered:

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

The 155-s session takes well under a second of wall time, and running it again writes an identical file. `fi30.okl` is an OKL (OperantKit Log) file: a header that records the schedule expression and the columns of each event type, then one tab-separated line per event.

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

To plot or analyze the log, use [session-analyzer](https://github.com/OperantKit/session-analyzer).

## Usage

`operant` has one subcommand, `run`. `--schedule` accepts any [contingency-dsl](https://github.com/OperantKit/contingency-dsl) expression that [contingency-py](https://github.com/OperantKit/contingency-py) can run, for example `"FR3"`, `"VI60s"`, or `"Conc(VI30s, VI60s, COD=2s)"` (COD: changeover delay). Give exactly one of `--exit-reinforcers` and `--exit-time`. `python -m operantkit_cli run ...` is the same command.

| Flag | Default | Meaning |
|---|---|---|
| `--schedule DSL` | required | contingency-dsl expression |
| `--output PATH` | required | Path of the OKL log to write |
| `--exit-reinforcers N` | one of these two is required | Stop after N reinforcers |
| `--exit-time SECONDS` | | Stop after SECONDS of session time |
| `--name NAME` | `session` | Session name written in the header |
| `--virtual-rate-hz HZ` | `1.0` | Response rate of the virtual subject (responses per second) |
| `--seed N` | `0` | Seed of the virtual subject's responding |
| `--reinforcer-duration SEC` | `0.5` | How long each reinforcer delivery lasts |
| `--poll-interval SEC` | `0.001` | Clock advance per idle step |
| `--max-steps N` | `5000` | Upper limit on loop steps (see Limitations) |
| `--max-duration SEC` | none | Optional limit on wall time |

**Concurrent schedules.** Each component of `Conc(...)` gets its own virtual operandum (the lever or key the subject responds on), with an independent responder seeded `--seed`, `--seed + 1`, and so on.

**Reproducible VI, VR, and VT values.** Variable values follow the Fleshler and Hoffman (1962) progression. `--seed` seeds only the subject; to fix the schedule values, seed them in the expression:

```bash
operant run --schedule $'@algorithm("fleshler-hoffman", n=12, seed=42)\nConc(VI30s, VI60s)' \
    --output conc.okl --exit-time 1800 --seed 0
```

The components receive seeds 42, 43, … in the order they are written.

## Limitations

- **Only the virtual subject.** The subject responds at a constant Poisson rate and does not change with reinforcement, so the log shows what the schedule program delivers, not what an animal would do. Serial-port and hardware-in-the-loop backends exist in [experiment-io](https://github.com/OperantKit/experiment-io) but cannot be selected from this command.
- **Long sessions need `--max-steps`.** With the default of 5000 steps, a session with more than about 5000 events stops with `RuntimeError: drive: did not finish within 5000 steps` and leaves a partial log. Raise the limit, for example `--max-steps 1000000`.
- **Fleshler–Hoffman only.** `@algorithm("arithmetic")` is rejected with an error.
- **Times are simulated.** Times in the log are session time on a simulated clock, not wall-clock time.

If you are setting this command up for an AI coding assistant, see [AGENTS.md](AGENTS.md).

## Development

From a clone of this repository, after installing the other packages with the `--no-deps` command above:

```bash
pip install --no-deps -e .
pip install pytest pytest-cov
pytest
```

`tests/test_readme_examples.py` runs the 30-second example in both READMEs and checks the counts and the last line shown there.

## References

Fleshler, M., & Hoffman, H. S. (1962). A progression for generating variable-interval schedules. *Journal of the Experimental Analysis of Behavior*, *5*(4), 529–530. https://doi.org/10.1901/jeab.1962.5-529

## License

MIT. See [LICENSE](LICENSE).
