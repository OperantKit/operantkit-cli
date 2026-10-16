"""Run the 30-second example in each README and check the output it documents."""

from __future__ import annotations

import re
import shlex
from collections import Counter
from pathlib import Path

import pytest

from operantkit_cli.cli import main

ROOT = Path(__file__).resolve().parent.parent
READMES = {"README.md": "## 30-second example", "README.ja.md": "## 30 秒で動く例"}
_BASH = re.compile(r"```bash\n(.*?)```", re.DOTALL)
_COUNT = re.compile(r"^#\s+(\d+) (\w+)$")


def _example(name: str) -> list[str]:
    text = (ROOT / name).read_text(encoding="utf-8")
    section = text.split(READMES[name], 1)[1]
    return _BASH.search(section).group(1).splitlines()


@pytest.mark.integration
@pytest.mark.parametrize("name", list(READMES))
def test_readme_30_second_example(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = _example(name)
    argv = shlex.split(lines[0])
    assert argv[0] == "operant"
    expected = {m.group(2): int(m.group(1)) for line in lines if (m := _COUNT.match(line))}
    expected_last = lines[-1].removeprefix("# ")

    monkeypatch.chdir(tmp_path)
    assert main(argv[1:]) == 0

    log = (tmp_path / "fi30.okl").read_text(encoding="utf-8").splitlines()
    body = [line for line in log if not line.startswith("#")]
    assert Counter(line.split("\t")[1] for line in body) == expected
    assert body[-1] == expected_last
