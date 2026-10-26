"""Command-line entry point for OperantKit sessions.

Runs an experiment declaratively: parse a contingency-dsl schedule
expression, build the runtime schedule, drive it via
``session_runner.SessionRunner`` through ``experiment_io.drive``, and
persist events through ``session_recorder.OklSink``.

Two backends supply the responses and receive the reinforcers:

- ``virtual`` (default): a seeded Poisson subject on a simulated clock.
- ``serial``: a device on a serial port speaking the experiment-io serial
  wire format, on the host's monotonic clock (requires pyserial).

Examples
--------
Run an FR(3) session against a virtual Poisson subject until 5
reinforcers have been delivered::

    operant run --schedule "FR3" --output fr3.okl \\
        --exit-reinforcers 5 --virtual-rate-hz 5.0

Run CRF against a device on a serial port until 20 reinforcers::

    operant run --backend serial --port /dev/cu.usbmodem1 \\
        --schedule "CRF" --output crf.okl --exit-reinforcers 20
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from contingency.bridge import from_dsl
from contingency.errors import ScheduleConfigError
from contingency.schedules.concurrent import Concurrent
from contingency_dsl import DslError, parse
from contingency_dsl.annotations.apparatus.extension import ApparatusExtension
from contingency_dsl.annotations.measurement.extension import MeasurementExtension
from contingency_dsl.annotations.stimulus.extension import StimulusExtension
from contingency_dsl.annotations.subjects.extension import SubjectsExtension
from contingency_dsl.annotations.temporal.extension import TemporalExtension
from contingency_dsl.extensions import ExtensionRegistry
from experiment_core import ReinforcementCountExit, TimeLimitExit
from experiment_io import drive
from experiment_io.hw.backends.serial import SerialOperandum, SerialReinforcer
from experiment_io.hw.backends.virtual import (
    ManualClock,
    MultiVirtualOperandum,
    MultiVirtualSubject,
    RecordingReinforcer,
    VirtualOperandum,
    VirtualSubject,
)
from session_recorder import OklSink
from session_runner import SessionConfig, SessionRunner, tee

# Step cap used with --exit-reinforcers when --max-steps is not given. The
# number of responses needed per reinforcer depends on the schedule, so no
# bound follows from the exit condition; this stops a schedule that never
# delivers a reinforcer (for example EXT) from running forever.
_REINFORCER_EXIT_MAX_STEPS = 1_000_000

# Step cap for the serial backend when --max-steps is not given. ``drive``
# counts every idle poll as a step, so on a real clock the step count grows
# with elapsed time (about 1,000 per second at the default poll interval)
# and says nothing about the session's length. The session is bounded by its
# exit condition and by --max-duration instead.
_SERIAL_MAX_STEPS = 2**62

DEFAULT_BAUD = 115200


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argparse parser."""
    parser = argparse.ArgumentParser(
        prog="operant",
        description=(
            "Run an OperantKit session declaratively, driven by a "
            "contingency-dsl schedule expression, against a virtual subject "
            "or a device on a serial port."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser(
        "run",
        help="Run a session and write an OKL v1 log.",
    )
    run.add_argument(
        "--schedule",
        required=True,
        metavar="DSL",
        help='contingency-dsl source, e.g. "FR3" or "Conc(VI30s, VI60s)".',
    )
    run.add_argument(
        "--output",
        required=True,
        type=Path,
        metavar="PATH",
        help="OKL v1 output path (.txt; parents created on demand).",
    )
    run.add_argument(
        "--name",
        default="session",
        help="Session name written to the session_meta record.",
    )

    exit_group = run.add_mutually_exclusive_group(required=True)
    exit_group.add_argument(
        "--exit-reinforcers",
        type=int,
        metavar="N",
        help="Stop after N reinforcers have been delivered.",
    )
    exit_group.add_argument(
        "--exit-time",
        type=float,
        metavar="SECONDS",
        help="Stop after SECONDS of session time have elapsed.",
    )

    run.add_argument(
        "--backend",
        choices=("virtual", "serial"),
        default="virtual",
        help="Where responses come from: the virtual subject (default) or a "
        "device on a serial port (--port).",
    )
    run.add_argument(
        "--port",
        default=None,
        metavar="DEVICE",
        help="Serial port of the device, e.g. /dev/cu.usbmodem1 or COM3 "
        "(--backend serial only).",
    )
    run.add_argument(
        "--baud",
        type=int,
        default=None,
        help=f"Baud rate of the serial port (--backend serial only; default {DEFAULT_BAUD}).",
    )
    run.add_argument(
        "--virtual-rate-hz",
        type=float,
        default=1.0,
        help="Poisson response rate of the virtual subject (Hz).",
    )
    run.add_argument(
        "--seed",
        type=int,
        default=0,
        help="RNG seed for the virtual subject only. Seed VI/VR/VT schedule values "
        "with the DSL annotation @algorithm(seed=...).",
    )
    run.add_argument(
        "--reinforcer-duration",
        type=float,
        default=0.5,
        help="Seconds the reinforcer is held active per delivery.",
    )
    run.add_argument(
        "--poll-interval",
        type=float,
        default=0.001,
        help="Wait per idle iteration (seconds): a virtual-clock advance, or a "
        "sleep with --backend serial.",
    )
    run.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Cap on session-loop steps (one per response, reinforcer delivery, or idle poll). "
        "Default (virtual): derived from --exit-time, or "
        f"{_REINFORCER_EXIT_MAX_STEPS:,} with --exit-reinforcers. "
        "Default (serial): no cap; the exit condition and --max-duration end "
        "the session.",
    )
    run.add_argument(
        "--max-duration",
        type=float,
        default=None,
        help="Optional wall-time ceiling (seconds).",
    )

    return parser


_ANNOTATIONS = ExtensionRegistry.build(
    ApparatusExtension(),
    MeasurementExtension(),
    StimulusExtension(),
    SubjectsExtension(),
    TemporalExtension(),
)


def _build_schedule(source: str):
    """Parse a DSL string and bridge it to a runtime schedule.

    Program-level annotations are accepted. ``@algorithm(seed=S)`` seeds
    the VI / VR / VT schedules so the session is reproducible.
    """
    ast = parse(source, extensions=_ANNOTATIONS)
    return from_dsl(ast)


def _build_exit(args: argparse.Namespace):
    if args.exit_reinforcers is not None:
        if args.exit_reinforcers < 1:
            raise ValueError("--exit-reinforcers must be >= 1")
        return ReinforcementCountExit(count=args.exit_reinforcers)
    if args.exit_time <= 0:
        raise ValueError("--exit-time must be > 0")
    return TimeLimitExit(limit=args.exit_time)


def _check_backend(args: argparse.Namespace, schedule) -> None:
    """Reject backend options that do not fit together or with the schedule."""
    if args.backend == "virtual":
        for flag, value in (("--port", args.port), ("--baud", args.baud)):
            if value is not None:
                raise ValueError(f"{flag} requires --backend serial")
        return
    if args.port is None:
        raise ValueError("--backend serial requires --port")
    if isinstance(schedule, Concurrent):
        # One port carries every operandum, and each SerialOperandum drops
        # the lines of the other operanda, so components would lose responses.
        raise ValueError(
            "--backend serial does not support concurrent schedules yet; "
            "use a single-operandum schedule"
        )


def _open_serial(port: str, baud: int):
    """Open ``port`` with pyserial for non-blocking reads."""
    try:
        import serial
    except ImportError as exc:
        raise ValueError(
            "--backend serial requires pyserial; install it with "
            '`pip install pyserial` (or `pip install "operantkit-cli[serial]"`)'
        ) from exc
    return serial.Serial(port, baud, timeout=0)


def _serial_clock() -> Callable[[], float]:
    """Return the session clock of the serial backend."""
    return time.monotonic


def _build_virtual_operanda(schedule, args: argparse.Namespace, clock: ManualClock) -> list:
    """Build one virtual operandum per schedule component.

    A concurrent schedule gets one independent Poisson responder per
    component (seeds ``seed``, ``seed + 1``, ...), so every component is
    exposed to responding. Any other schedule gets a single operandum.
    """
    if isinstance(schedule, Concurrent):
        n = len(schedule.components)
        subject = MultiVirtualSubject(
            rates_hz=[args.virtual_rate_hz] * n,
            seeds=[args.seed + i for i in range(n)],
        )
        return MultiVirtualOperandum(subject, clock).split()
    subject = VirtualSubject(rate_hz=args.virtual_rate_hz, seed=args.seed)
    return [VirtualOperandum(0, subject, clock)]


def _max_steps(args: argparse.Namespace, n_operanda: int) -> int:
    """Return the step cap for ``drive``.

    Each virtual poll yields one response and each reinforcer delivery
    takes one further step, so a session runs at most two steps per
    response. With ``--exit-time`` the response count is Poisson with mean
    ``rate * operanda * time``; the cap allows ten standard deviations
    above that mean, so the time limit is what ends the session.
    """
    if args.max_steps is not None:
        return args.max_steps
    if args.backend == "serial":
        return _SERIAL_MAX_STEPS
    if args.exit_reinforcers is not None:
        return _REINFORCER_EXIT_MAX_STEPS
    mean = max(args.virtual_rate_hz, 0.0) * n_operanda * args.exit_time
    return 2 * math.ceil(mean + 10 * math.sqrt(mean) + 100)


def run(args: argparse.Namespace, schedule, exit_condition, port=None) -> int:
    """Execute the ``run`` subcommand with already-validated inputs.

    ``port`` is the opened serial port with ``--backend serial``.
    """
    if port is None:
        clock: Callable[[], float] = ManualClock()
        operanda = _build_virtual_operanda(schedule, args, clock)
        reinforcers = [RecordingReinforcer(operandum_index=i) for i in range(len(operanda))]
        clock_type = type(clock).__name__
        metadata = {"dsl": args.schedule}
    else:
        clock = _serial_clock()
        operanda = [SerialOperandum(port, 0)]
        reinforcers = [SerialReinforcer(port, 0)]
        clock_type = "monotonic"
        metadata = {"dsl": args.schedule, "backend": "serial"}
        # Lines the device sent before the session belong to no session.
        reset = getattr(port, "reset_input_buffer", None)
        if callable(reset):
            reset()

    start = clock()
    sink = OklSink(args.output)
    sink.write_header(
        session_name=args.name,
        clock_type=clock_type,
        session_start=start,
        metadata=metadata,
    )

    runner = SessionRunner(
        SessionConfig(
            name=args.name,
            schedule=schedule,
            exit_condition=exit_condition,
            metadata=metadata,
        ),
        sink=tee(sink),
        clock=clock,
    )
    runner.start(start_time=start)
    drive(
        runner,
        operanda=operanda,
        reinforcers=reinforcers,
        clock=clock,
        reinforcer_duration=args.reinforcer_duration,
        max_duration=args.max_duration,
        max_steps=_max_steps(args, len(operanda)),
        poll_interval=args.poll_interval,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point used by the ``operant`` console script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        # Only invalid user input is reported as a one-line error; failures
        # inside the session run propagate with their traceback.
        try:
            schedule = _build_schedule(args.schedule)
            exit_condition = _build_exit(args)
            _check_backend(args, schedule)
            port = (
                _open_serial(args.port, args.baud or DEFAULT_BAUD)
                if args.backend == "serial"
                else None
            )
        except (DslError, ScheduleConfigError, ValueError, OSError) as exc:
            print(f"{parser.prog}: error: {exc}", file=sys.stderr)
            return 2
        try:
            return run(args, schedule, exit_condition, port)
        finally:
            # ``drive`` closes the port when it returns; this covers a failure
            # before the loop starts (closing pyserial twice is harmless).
            if port is not None:
                port.close()
    parser.error(f"unknown command: {args.command!r}")
    return 2  # unreachable; argparse exits in error()


if __name__ == "__main__":
    raise SystemExit(main())
