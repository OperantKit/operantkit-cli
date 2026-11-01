"""Tests for ``operant run --decision {host,device}``.

With ``--decision device`` the device on the serial port decides the
contingency: the host sends ``load`` and ``start`` and records what the
device reports. The fake device here answers that protocol on a
``ManualClock`` and runs CRF: every press is reinforced, until
``stop_after.reinforcers``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from experiment_io.hw.backends.virtual import ManualClock
from session_recorder import read_log

import operantkit_cli.cli as cli
from operantkit_cli.cli import main

CLOCK_START = 5000.0
DEVICE_START = 12.0


class FakeDevice:
    """A device that decides CRF itself and speaks the JSON-line protocol."""

    def __init__(self, clock: ManualClock, *, interval: float = 0.3) -> None:
        self.clock = clock
        self.interval = interval
        self.commands: list[dict] = []
        self.out: list[dict] = []
        self.closed = False
        self.running = False
        self.seq = 0
        self.n_sr = 0
        self.stop_after = 0
        self.duration = 0.0
        self.next_press = 0.0
        self.host_start = 0.0

    def _emit(self, kind: str, **fields: object) -> None:
        self.seq += 1
        self.out.append({"kind": kind, "seq": self.seq, **fields})

    def _device_ts(self, host_time: float) -> float:
        return DEVICE_START + (host_time - self.host_start)

    def _advance(self) -> None:
        while self.running and self.next_press <= self.clock():
            ts = self._device_ts(self.next_press)
            self._emit("response", op=0, ts=ts)
            self.n_sr += 1
            self._emit("reinforcer_start", op=0, ts=ts)
            self._emit("reinforcer_end", op=0, ts=ts + self.duration)
            self.next_press += self.interval
            if self.n_sr >= self.stop_after:
                self.running = False
                self._emit("stopped", ts=ts + self.duration)

    def write(self, data: object) -> int:
        if not isinstance(data, bytes):
            raise TypeError("unicode strings are not supported, please encode to bytes")
        command = json.loads(data.decode())
        self.commands.append(command)
        cmd = command["cmd"]
        if cmd == "load":
            self.stop_after = command["stop_after"]["reinforcers"]
            self.duration = command["reinforcer"]["duration"]
            self.out.append({"kind": "loaded", "firmware": "fake-1"})
        elif cmd == "start":
            self.running = True
            self.host_start = self.clock()
            self.next_press = self.host_start + self.interval
            self.seq = 0
            self.out.append({"kind": "started", "ts": DEVICE_START, "seq": 0})
        elif cmd == "stop":
            self.running = False
        elif cmd == "report":
            self.out.append({"kind": "report", "reinforcers": self.n_sr})
        return len(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        self._advance()
        if not self.out:
            self.clock.advance(0.05)  # a read timeout passes time
            return b""
        return (json.dumps(self.out.pop(0)) + "\n").encode()

    def reset_input_buffer(self) -> None:
        self.out.clear()

    def close(self) -> None:
        self.closed = True

    def sent(self, cmd: str) -> bool:
        return any(c["cmd"] == cmd for c in self.commands)


@pytest.fixture
def device(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Route ``--backend serial`` to a ``FakeDevice`` on a manual clock."""
    clock = ManualClock()
    clock.advance(CLOCK_START)
    opened: dict = {"ports": []}

    def open_fake(port: str, baud: int) -> FakeDevice:
        fake = FakeDevice(clock)
        opened["ports"].append(fake)
        return fake

    monkeypatch.setattr(cli, "_open_serial", open_fake)
    monkeypatch.setattr(cli, "_serial_clock", lambda: clock)
    return opened


def _argv(output: Path, schedule: str, *extra: str) -> list[str]:
    return [
        "run",
        "--backend",
        "serial",
        "--port",
        "/dev/cu.fake",
        "--schedule",
        schedule,
        "--output",
        str(output),
        "--exit-reinforcers",
        "5",
        *extra,
    ]


@pytest.mark.integration
def test_without_decision_the_host_decides(tmp_path: Path, device: dict) -> None:
    output = tmp_path / "x.okl"
    assert main(_argv(output, "CRF", "--max-duration", "2")) == 0
    (port,) = device["ports"]
    assert not port.sent("load")
    assert not port.sent("start")
    meta = read_log(output).meta
    assert meta.metadata.get("decision") == "host"
    assert meta.clock_type == "monotonic"


def test_virtual_sessions_say_the_host_decides(tmp_path: Path) -> None:
    output = tmp_path / "x.okl"
    rc = main(["run", "--schedule", "FR3", "--output", str(output), "--exit-reinforcers", "2"])
    assert rc == 0
    assert read_log(output).meta.metadata.get("decision") == "host"


@pytest.mark.parametrize(
    "schedule",
    ["Chain(FR3, FI10s)", "Conc(VI30s, VI60s)", "VI30s"],
    ids=["not-on-device", "concurrent", "random-without-seed"],
)
def test_device_refuses_before_anything_starts(
    tmp_path: Path, device: dict, capsys: pytest.CaptureFixture[str], schedule: str
) -> None:
    output = tmp_path / "x.okl"
    rc = main(_argv(output, schedule, "--decision", "device"))
    assert rc == 2
    err = capsys.readouterr().err
    assert err.startswith("operant: error: ")
    assert "--decision host" in err
    assert not output.exists()
    assert all(not port.sent("start") for port in device["ports"])


@pytest.mark.integration
def test_device_crf_is_logged_on_the_device_clock(tmp_path: Path, device: dict) -> None:
    output = tmp_path / "x.okl"
    assert main(_argv(output, "CRF", "--decision", "device", "--reinforcer-duration", "0.05")) == 0
    (port,) = device["ports"]
    assert port.closed
    (load,) = [c for c in port.commands if c["cmd"] == "load"]
    assert load["schedule"] == {"type": "CRF", "params": {}}
    assert load["stop_after"] == {"reinforcers": 5}
    assert load["reinforcer"] == {"op": 0, "duration": 0.05}

    log = read_log(output)
    assert log.meta.metadata.get("decision") == "device"
    assert log.meta.clock_type == "device"
    assert log.meta.metadata.get("device_firmware") == "fake-1"
    assert log.meta.timestamp == DEVICE_START
    types = [r.type for r in log.raw_records]
    assert types.count("response") == 5
    assert types.count("reinforcer_start") == 5
    assert types.count("reinforcer_end") == 5


@pytest.mark.integration
def test_device_runs_a_seeded_random_schedule(tmp_path: Path, device: dict) -> None:
    output = tmp_path / "x.okl"
    schedule = '@algorithm("fleshler-hoffman", seed=7)\nVI30s'
    assert main(_argv(output, schedule, "--decision", "device")) == 0
    (port,) = device["ports"]
    (load,) = [c for c in port.commands if c["cmd"] == "load"]
    assert load["schedule"] == {"type": "VI", "params": {"mean_interval": 30.0, "seed": 7}}


def test_device_decision_needs_the_serial_backend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "x.okl"
    argv = ["run", "--schedule", "CRF", "--output", str(output), "--exit-reinforcers", "2"]
    assert main([*argv, "--decision", "device"]) == 2
    assert "--decision requires --backend serial" in capsys.readouterr().err
    assert not output.exists()


def test_device_decision_needs_a_reinforcer_count(
    tmp_path: Path, device: dict, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "x.okl"
    argv = [
        "run", "--backend", "serial", "--port", "/dev/cu.fake", "--schedule", "CRF",
        "--output", str(output), "--exit-time", "10", "--decision", "device",
    ]  # fmt: skip
    assert main(argv) == 2
    assert "--exit-reinforcers" in capsys.readouterr().err
    assert not output.exists()
    assert device["ports"] == []
