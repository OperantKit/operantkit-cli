# operantkit-cli

:jp: [日本語版 README](README.ja.md)

`operant run` runs one session of a reinforcement schedule against a simulated subject and writes every event to a plain-text log, without writing any code. It is the command-line entry point of [OperantKit](https://github.com/OperantKit): it parses the schedule with contingency-dsl-py, runs it with contingency-py, experiment-core, session-runner, and experiment-io, and writes the log with session-recorder.

- **One expression in, one log out.** `--schedule "Conc(VI30s, VI60s, COD=2s)"` is the whole procedure.
- **Seconds, not hours.** Session time is simulated, and the same seeds write the same log byte for byte.
- **Mistakes stop before the session.** An invalid schedule prints one error line and writes no log.

Use it to see what a schedule program actually delivers before an animal runs on it, to make example data for teaching, or to feed an analysis pipeline with a log of known content.

## Installation


Python 3.11 or newer. The packages are not on PyPI yet, so install them from GitHub together:

```bash
# Until the PyPI release, install from GitHub together with its OperantKit dependencies.
pip install git+https://github.com/OperantKit/contingency-dsl-py \
            git+https://github.com/OperantKit/contingency-py \
            git+https://github.com/OperantKit/experiment-core \
            git+https://github.com/OperantKit/session-runner \
            git+https://github.com/OperantKit/session-recorder \
            git+https://github.com/OperantKit/experiment-io \
            git+https://github.com/OperantKit/operantkit-cli
```

No third-party library is needed. pip resolves the dependencies between them, and `pip check` reports nothing.

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
| `--backend NAME` | `virtual` | `virtual` (simulated subject) or `serial` (a device on a serial port) |
| `--port DEVICE` | none | Serial port, for example `/dev/cu.usbmodem1` or `COM3` (`--backend serial` only) |
| `--baud N` | `115200` | Baud rate of the serial port (`--backend serial` only) |
| `--virtual-rate-hz HZ` | `1.0` | Response rate of the virtual subject (responses per second) |
| `--seed N` | `0` | Seed of the virtual subject's responding |
| `--reinforcer-duration SEC` | `0.5` | How long each reinforcer delivery lasts |
| `--poll-interval SEC` | `0.001` | Wait per idle step (a clock advance, or a sleep with `--backend serial`) |
| `--max-steps N` | derived | Upper limit on loop steps (see Limitations) |
| `--max-duration SEC` | none | Optional limit on wall time |

**Concurrent schedules.** Each component of `Conc(...)` gets its own virtual operandum (the lever or key the subject responds on), with an independent responder seeded `--seed`, `--seed + 1`, and so on.

**Reproducible VI, VR, and VT values.** Variable values follow the Fleshler and Hoffman (1962) progression. `--seed` seeds only the subject; to fix the schedule values, seed them in the expression:

```bash
operant run --schedule $'@algorithm("fleshler-hoffman", n=12, seed=42)\nConc(VI30s, VI60s)' \
    --output conc.okl --exit-time 1800 --seed 0
```

The components receive seeds 42, 43, … in the order they are written.

**A device on a serial port.** `--backend serial --port DEVICE` takes responses from a device (for example a microcontroller wired to a lever and a feeder) instead of the virtual subject, on the computer's monotonic clock. It needs pyserial (`pip install pyserial`). The device speaks the [experiment-io](https://github.com/OperantKit/experiment-io) serial format, one JSON object per line:

```text
device -> computer   {"op": 0, "ts": 12.345, "kind": "response"}
computer -> device   {"cmd": "reinforcer", "op": 0, "duration": 0.5}
```

```bash
operant run --backend serial --port /dev/cu.usbmodem1 --schedule "CRF" \
    --output crf.okl --exit-reinforcers 20
```

Lines that arrived before the session starts are discarded. Session times are the computer's receipt times; the device's `ts` is not written to the log. The header has `clock_type = "monotonic"`, `backend = "serial"`, and `session_start` (the clock reading at the start; event times are on the same clock, so subtract it for times from the session start). Commands that a particular device needs before or after a session (for example to start or stop it) are not sent.

## Limitations

- **The virtual subject does not learn.** It responds at a constant Poisson rate and does not change with reinforcement, so a virtual log shows what the schedule program delivers, not what an animal would do.
- **Serial: one operandum.** `--backend serial` rejects concurrent schedules, because every operandum would share one port. The hardware-in-the-loop backend of experiment-io cannot be selected from this command.
- **Step limit.** Each response and each reinforcer delivery is one loop step. With `--exit-time`, the default limit is set from the session time and the response rate, so the time limit ends the session. With `--exit-reinforcers`, the default limit is 1,000,000 steps, which stops a schedule that never delivers a reinforcer (for example `EXT`). A session that reaches the limit stops with `RuntimeError: drive: did not finish within N steps` and leaves a partial log; give a larger `--max-steps N` if needed. With `--backend serial` every idle poll is also a step, so there is no default limit; the exit condition and `--max-duration` end the session (with a schedule that never delivers a reinforcer, such as `EXT`, and `--exit-reinforcers`, give `--max-duration`).
- **Fleshler–Hoffman only.** `@algorithm("arithmetic")` is rejected with an error.
- **Virtual times are simulated.** With `--backend virtual`, times in the log are session time on a simulated clock, not wall-clock time.

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
