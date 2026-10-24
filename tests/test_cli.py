"""Tests for the ``operant`` CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from session_recorder import read_log

from operantkit_cli.cli import _build_exit, _build_schedule, build_parser, main


@pytest.mark.unit
def test_build_parser_run_requires_schedule_output_and_exit() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run"])
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--schedule", "FR1", "--exit-reinforcers", "1"])
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--schedule", "FR1", "--output", "x.txt"])


@pytest.mark.unit
def test_build_parser_exit_options_mutually_exclusive() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "run",
                "--schedule",
                "FR1",
                "--output",
                "x.txt",
                "--exit-reinforcers",
                "1",
                "--exit-time",
                "5",
            ]
        )


@pytest.mark.unit
def test_build_schedule_parses_fr() -> None:
    schedule = _build_schedule("FR3")
    assert type(schedule).__name__ == "FR"


@pytest.mark.unit
def test_build_exit_reinforcers() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["run", "--schedule", "FR1", "--output", "x.txt", "--exit-reinforcers", "5"]
    )
    exit_cond = _build_exit(args)
    assert exit_cond.__class__.__name__ == "ReinforcementCountExit"
    assert exit_cond.count == 5


@pytest.mark.unit
def test_build_exit_time() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["run", "--schedule", "FR1", "--output", "x.txt", "--exit-time", "10.5"]
    )
    exit_cond = _build_exit(args)
    assert exit_cond.__class__.__name__ == "TimeLimitExit"
    assert exit_cond.limit == 10.5


@pytest.mark.unit
def test_build_exit_rejects_zero_reinforcers() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["run", "--schedule", "FR1", "--output", "x.txt", "--exit-reinforcers", "0"]
    )
    with pytest.raises(ValueError, match="exit-reinforcers"):
        _build_exit(args)


@pytest.mark.unit
def test_build_exit_rejects_nonpositive_time() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["run", "--schedule", "FR1", "--output", "x.txt", "--exit-time", "0"]
    )
    with pytest.raises(ValueError, match="exit-time"):
        _build_exit(args)


@pytest.mark.integration
def test_main_runs_fr1_session_and_writes_log(tmp_path: Path) -> None:
    output = tmp_path / "session.txt"
    rc = main(
        [
            "run",
            "--schedule",
            "FR1",
            "--output",
            str(output),
            "--exit-reinforcers",
            "3",
            "--virtual-rate-hz",
            "10.0",
            "--seed",
            "0",
            "--reinforcer-duration",
            "0.1",
        ]
    )
    assert rc == 0
    assert output.exists()
    log = read_log(output)
    types = [r.type for r in log.raw_records]
    assert sum(1 for t in types if t == "reinforcer_start") == 3
    assert sum(1 for t in types if t == "reinforcer_end") == 3


@pytest.mark.integration
def test_main_run_records_dsl_in_metadata(tmp_path: Path) -> None:
    output = tmp_path / "session.txt"
    main(
        [
            "run",
            "--schedule",
            "FR2",
            "--output",
            str(output),
            "--exit-reinforcers",
            "1",
            "--virtual-rate-hz",
            "20.0",
        ]
    )
    log = read_log(output)
    assert log.meta.metadata.get("dsl") == "FR2"


@pytest.mark.integration
def test_main_run_with_time_limit_terminates(tmp_path: Path) -> None:
    output = tmp_path / "session.txt"
    rc = main(
        [
            "run",
            "--schedule",
            "FI1s",
            "--output",
            str(output),
            "--exit-time",
            "0.5",
            "--virtual-rate-hz",
            "0.1",
            "--poll-interval",
            "0.01",
        ]
    )
    assert rc == 0
    assert output.exists()


@pytest.mark.unit
def test_main_unknown_command_exits() -> None:
    with pytest.raises(SystemExit):
        main(["nope"])


@pytest.mark.integration
def test_main_run_concurrent_drives_every_component(tmp_path: Path) -> None:
    """A ``Conc(...)`` schedule gets one virtual operandum per component."""
    from experiment_core import ReinforcerStartEvent, ResponseEvent

    output = tmp_path / "conc.txt"
    rc = main(
        [
            "run",
            "--schedule",
            "Conc(VI30s, VI60s)",
            "--output",
            str(output),
            "--exit-time",
            "600",
            "--virtual-rate-hz",
            "2.0",
            "--seed",
            "0",
        ]
    )
    assert rc == 0
    events = read_log(output).events
    response_ops = {e.operandum for e in events if isinstance(e, ResponseEvent)}
    reinforced_ops = {e.operandum for e in events if isinstance(e, ReinforcerStartEvent)}
    assert response_ops == {0, 1}
    assert reinforced_ops == {0, 1}


@pytest.mark.integration
def test_main_run_algorithm_seed_reproduces_concurrent_session(tmp_path: Path) -> None:
    """``@algorithm(seed=...)`` in the DSL makes VI sessions reproducible."""
    source = '@algorithm("fleshler-hoffman", n=12, seed=1)\nConc(VI30s, VI60s)'
    outputs = [tmp_path / "a.txt", tmp_path / "b.txt"]
    for output in outputs:
        rc = main(
            [
                "run",
                "--schedule",
                source,
                "--output",
                str(output),
                "--exit-time",
                "600",
                "--seed",
                "0",
            ]
        )
        assert rc == 0
    assert outputs[0].read_text() == outputs[1].read_text()


@pytest.mark.integration
@pytest.mark.parametrize(
    "schedule",
    ["FR", '@algorithm("arithmetic", seed=1)\nVI30s'],
)
def test_main_run_reports_invalid_schedule_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], schedule: str
) -> None:
    rc = main(
        ["run", "--schedule", schedule, "--output", str(tmp_path / "x.txt"), "--exit-time", "5"]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert err.startswith("operant: error: ")
    assert "Traceback" not in err


@pytest.mark.integration
def test_main_run_lets_internal_errors_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only input errors become ``operant: error``; runtime bugs propagate."""
    import operantkit_cli.cli as cli

    def broken_drive(*_args: object, **_kwargs: object) -> None:
        raise ValueError("internal bug in driver")

    monkeypatch.setattr(cli, "drive", broken_drive)
    with pytest.raises(ValueError, match="internal bug"):
        main(
            ["run", "--schedule", "FR1", "--output", str(tmp_path / "x.txt"), "--exit-time", "5"]
        )


@pytest.mark.integration
def test_main_run_invalid_schedule_writes_no_log(tmp_path: Path) -> None:
    output = tmp_path / "x.txt"
    rc = main(["run", "--schedule", "FR", "--output", str(output), "--exit-time", "5"])
    assert rc == 2
    assert not output.exists()


@pytest.mark.integration
def test_main_run_hour_long_concurrent_session_finishes(tmp_path: Path) -> None:
    """A one-hour ``--exit-time`` session is not cut short by the step cap."""
    output = tmp_path / "c2.okl"
    rc = main(
        [
            "run",
            "--schedule",
            "Conc(VI 135-s, VI 270-s, COD=1.5-s)",
            "--output",
            str(output),
            "--exit-time",
            "3600",
        ]
    )
    assert rc == 0
    last = [line for line in output.read_text().splitlines() if not line.startswith("#")][-1]
    time, event, *fields = last.split("\t")
    assert (event, fields) == ("state_change", ["RUNNING", "FINISHED"])
    assert 3600 <= float(time) < 3610
