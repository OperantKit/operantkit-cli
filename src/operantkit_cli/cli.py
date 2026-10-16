"""Command-line entry point for OperantKit sessions.

Runs an experiment declaratively: parse a contingency-dsl schedule
expression, build the runtime schedule, drive it via
``session_runner.SessionRunner`` against a virtual subject through
``experiment_io.drive``, and persist events through
``session_recorder.OklSink``.

Examples
--------
Run an FR(3) session against a virtual Poisson subject until 5
reinforcers have been delivered::

    operant run --schedule "FR3" --output fr3.okl \\
        --exit-reinforcers 5 --virtual-rate-hz 5.0
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
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


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level argparse parser."""
    parser = argparse.ArgumentParser(
        prog="operant",
        description=(
            "Run an OperantKit session declaratively, driven by a "
            "contingency-dsl schedule expression and virtual hardware."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser(
        "run",
        help="Run a session against a virtual subject and write an OKL v1 log.",
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
        'with the DSL annotation @algorithm(seed=...).',
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
        help="Virtual-clock advance per idle iteration (seconds).",
    )
    run.add_argument(
        "--max-steps",
        type=int,
        default=5_000,
        help="Hard cap on hardware-loop iterations.",
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


def run(args: argparse.Namespace, schedule, exit_condition) -> int:
    """Execute the ``run`` subcommand with already-validated inputs."""

    clock = ManualClock()
    operanda = _build_virtual_operanda(schedule, args, clock)
    reinforcers = [RecordingReinforcer(operandum_index=i) for i in range(len(operanda))]

    sink = OklSink(args.output)
    sink.write_header(
        session_name=args.name,
        clock_type=type(clock).__name__,
        session_start=0.0,
        metadata={"dsl": args.schedule},
    )

    runner = SessionRunner(
        SessionConfig(
            name=args.name,
            schedule=schedule,
            exit_condition=exit_condition,
            metadata={"dsl": args.schedule},
        ),
        sink=tee(sink),
        clock=clock,
    )
    runner.start(start_time=clock())
    drive(
        runner,
        operanda=operanda,
        reinforcers=reinforcers,
        clock=clock,
        reinforcer_duration=args.reinforcer_duration,
        max_duration=args.max_duration,
        max_steps=args.max_steps,
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
        except (DslError, ScheduleConfigError, ValueError) as exc:
            print(f"{parser.prog}: error: {exc}", file=sys.stderr)
            return 2
        return run(args, schedule, exit_condition)
    parser.error(f"unknown command: {args.command!r}")
    return 2  # unreachable; argparse exits in error()


if __name__ == "__main__":
    raise SystemExit(main())
