"""Every code file — package, tests, and vendored skills alike — stays under 1000 lines.

A file that grows past that is a file nobody reads end to end; split it. The
limit covers *all code surfaces* (source, tests, skill scripts, workflows,
configs), so a vendored skill script that outgrows it is a finding to raise
upstream, not to patch here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

MAX_LINES = 1000
CODE_SUFFIXES = {".py", ".sh", ".bash", ".js", ".ts", ".yaml", ".yml", ".toml", ".json"}
ROOT = Path(__file__).resolve().parents[1]


def _tracked_code_files() -> list[Path]:
    out = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    files = [ROOT / name for name in out.decode().split("\0") if name]
    return sorted(f for f in files if f.suffix in CODE_SUFFIXES and f.is_file())


@pytest.mark.parametrize("path", _tracked_code_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_code_file_is_under_the_line_limit(path: Path) -> None:
    lines = path.read_text(encoding="utf-8", errors="replace").count("\n")
    assert lines <= MAX_LINES, f"{path.relative_to(ROOT)} has {lines} lines (limit {MAX_LINES})"
