"""Tests for ``operant run --backend serial``.

The serial port is replaced by a fake that behaves like a pyserial
``Serial`` opened with ``timeout=0``: ``readline`` returns ``bytes`` (an
empty ``bytes`` when nothing has arrived) and ``write`` accepts ``bytes``
only. The device sends a response line every ``interval`` seconds stamped
with its own clock, and each line reaches the host ``delay`` seconds
later. Time is a ``ManualClock`` started at ``CLOCK_START`` (a monotonic
clock does not start at zero), so no test waits on the wall clock.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from experiment_io.hw.backends.virtual import ManualClock
from session_recorder import read_log

import operantkit_cli.cli as cli
from operantkit_cli.cli import main

CLOCK_START = 5000.0


def _body_times(output: Path) -> list[float]:
    """Event times in the log, measured from the header's session_start."""
    start = read_log(output).meta.timestamp
    lines = [line for line in output.read_text().splitlines() if not line.startswith("#")]
    return [float(line.split("\t")[0]) - start for line in lines]


class FakeSerial:
    """A device that responds every ``interval`` s, seen through a pyserial-like port."""

    def __init__(
        self,
        clock: ManualClock,
        *,
        interval: float = 0.3,
        delay: float = 0.002,
        device_offset: float = 1000.0,
        stale_lines: int = 0,
    ) -> None:
        self.clock = clock
        self.interval = interval
        self.delay = delay
        self.device_offset = device_offset
        self.next_press = clock() + interval
        self.buffer = b"".join(self._line(-1.0 - i) for i in range(stale_lines))
        self.commands: list[dict] = []
        self.closed = False
        self.resets = 0

    def _line(self, ts: float) -> bytes:
        return (json.dumps({"op": 0, "ts": ts, "kind": "response"}) + "\n").encode()

    def _arrive(self) -> None:
        now = self.clock()
        while self.next_press + self.delay <= now:
            self.buffer += self._line(self.next_press + self.device_offset)
            self.next_press += self.interval

    def readline(self) -> bytes:
        self._arrive()
        if b"\n" not in self.buffer:
            return b""
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line + b"\n"

    def write(self, data: object) -> int:
        if not isinstance(data, bytes):
            raise TypeError("unicode strings are not supported, please encode to bytes")
        self.commands.append(json.loads(data.decode()))
        return len(data)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        self._arrive()
        self.buffer = b""
        self.resets += 1

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_port(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Route ``--backend serial`` to a ``FakeSerial`` on a manual clock."""
    clock = ManualClock()
    clock.advance(CLOCK_START)
    opened: dict = {"clock": clock, "ports": [], "kwargs": {}}

    def open_fake(port: str, baud: int) -> FakeSerial:
        opened["args"] = (port, baud)
        fake = FakeSerial(clock, **opened["kwargs"])
        opened["ports"].append(fake)
        return fake

    monkeypatch.setattr(cli, "_open_serial", open_fake)
    monkeypatch.setattr(cli, "_serial_clock", lambda: clock)
    return opened


def _serial_argv(output: Path, *extra: str) -> list[str]:
    return [
        "run",
        "--backend",
        "serial",
        "--port",
        "/dev/cu.fake",
        "--schedule",
        "CRF",
        "--output",
        str(output),
        *extra,
    ]


@pytest.mark.integration
def test_serial_crf_delivers_reinforcers_to_the_port(tmp_path: Path, fake_port: dict) -> None:
    output = tmp_path / "x.okl"
    rc = main(_serial_argv(output, "--exit-reinforcers", "20", "--reinforcer-duration", "0.05"))
    assert rc == 0
    assert fake_port["args"] == ("/dev/cu.fake", 115200)
    (port,) = fake_port["ports"]
    assert port.closed
    assert port.commands == [{"cmd": "reinforcer", "op": 0, "duration": 0.05}] * 20

    log = read_log(output)
    types = [r.type for r in log.raw_records]
    assert types.count("reinforcer_start") == 20
    assert types.count("reinforcer_end") == 20
    assert types.count("response") == 20
    assert log.meta.clock_type == "monotonic"
    assert log.meta.metadata.get("backend") == "serial"
    assert log.meta.metadata.get("dsl") == "CRF"
    assert log.meta.timestamp == CLOCK_START  # session_start


@pytest.mark.integration
def test_serial_session_times_follow_the_host_clock(tmp_path: Path, fake_port: dict) -> None:
    """Response times are host receipt times, not the device's own stamps."""
    output = tmp_path / "x.okl"
    assert main(_serial_argv(output, "--exit-reinforcers", "3")) == 0
    times = _body_times(output)
    assert times[0] == 0.0  # IDLE -> RUNNING at session_start
    assert times == sorted(times)
    assert max(times) < 100  # the device clock runs 1000 s ahead


@pytest.mark.integration
def test_serial_exit_time_is_not_cut_short_by_the_step_cap(tmp_path: Path, fake_port: dict) -> None:
    """Idle polls count as steps; a 30-s session at 1 ms polls takes ~30,000."""
    output = tmp_path / "x.okl"
    rc = main(_serial_argv(output, "--exit-time", "30", "--reinforcer-duration", "0.05"))
    assert rc == 0
    last = [line for line in output.read_text().splitlines() if not line.startswith("#")][-1]
    _, event, *fields = last.split("\t")
    assert (event, fields) == ("state_change", ["RUNNING", "FINISHED"])
    assert 30 <= _body_times(output)[-1] < 30.1


@pytest.mark.integration
def test_serial_drops_lines_that_arrived_before_the_session(
    tmp_path: Path, fake_port: dict
) -> None:
    fake_port["kwargs"]["stale_lines"] = 5
    output = tmp_path / "x.okl"
    assert main(_serial_argv(output, "--exit-reinforcers", "1")) == 0
    (port,) = fake_port["ports"]
    assert port.resets == 1
    lines = [line for line in output.read_text().splitlines() if not line.startswith("#")]
    first_response = next(i for i, line in enumerate(lines) if "\tresponse\t" in line)
    assert _body_times(output)[first_response] >= 0.3


@pytest.mark.integration
def test_serial_requires_a_port(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "x.okl"
    rc = main(
        [
            "run",
            "--backend",
            "serial",
            "--schedule",
            "CRF",
            "--output",
            str(output),
            "--exit-reinforcers",
            "1",
        ]
    )
    assert rc == 2
    assert capsys.readouterr().err.startswith("operant: error: --backend serial requires --port")
    assert not output.exists()


@pytest.mark.integration
def test_port_without_serial_backend_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "x.okl"
    rc = main(
        [
            "run",
            "--port",
            "/dev/cu.fake",
            "--schedule",
            "CRF",
            "--output",
            str(output),
            "--exit-reinforcers",
            "1",
        ]
    )
    assert rc == 2
    assert "--port" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.integration
def test_serial_rejects_concurrent_schedules(
    tmp_path: Path, fake_port: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "x.okl"
    argv = _serial_argv(output, "--exit-time", "5")
    argv[argv.index("CRF")] = "Conc(VI30s, VI60s)"
    assert main(argv) == 2
    assert "concurrent" in capsys.readouterr().err
    assert fake_port["ports"] == []
    assert not output.exists()


@pytest.mark.integration
def test_serial_port_open_failure_is_an_input_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(port: str, baud: int) -> FakeSerial:
        raise OSError(2, "No such file or directory", port)

    monkeypatch.setattr(cli, "_open_serial", refuse)
    output = tmp_path / "x.okl"
    assert main(_serial_argv(output, "--exit-reinforcers", "1")) == 2
    err = capsys.readouterr().err
    assert err.startswith("operant: error: ")
    assert "/dev/cu.fake" in err
    assert not output.exists()


@pytest.mark.integration
def test_serial_without_pyserial_says_how_to_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "serial", None)
    output = tmp_path / "x.okl"
    assert main(_serial_argv(output, "--exit-reinforcers", "1")) == 2
    assert "pyserial" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.integration
def test_serial_port_is_closed_when_the_session_fails_to_start(
    tmp_path: Path, fake_port: dict
) -> None:
    """A failure before ``drive`` (here: a non-empty output file) still closes the port."""
    output = tmp_path / "x.okl"
    output.write_text("not empty\n")
    with pytest.raises(RuntimeError):
        main(_serial_argv(output, "--exit-reinforcers", "1"))
    (port,) = fake_port["ports"]
    assert port.closed


@pytest.mark.integration
def test_baud_without_serial_backend_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "x.okl"
    rc = main(
        [
            "run",
            "--baud",
            "9600",
            "--schedule",
            "CRF",
            "--output",
            str(output),
            "--exit-reinforcers",
            "1",
        ]
    )
    assert rc == 2
    assert "--baud requires --backend serial" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.integration
def test_serial_passes_the_baud_rate(tmp_path: Path, fake_port: dict) -> None:
    output = tmp_path / "x.okl"
    assert main(_serial_argv(output, "--baud", "9600", "--exit-reinforcers", "1")) == 0
    assert fake_port["args"] == ("/dev/cu.fake", 9600)
