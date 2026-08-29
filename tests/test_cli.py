"""Smoke tests for the notion-agent CLI entry point and its verbs."""

from __future__ import annotations

import argparse
import json

import pytest

from notion_agent import __version__
from notion_agent.cli import _build_parser, main
from notion_agent.explain import known_paths


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([])
    assert rc == 0
    assert "usage: notion-agent" in capsys.readouterr().out


def test_unknown_command_errors(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["bogus"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


# --- whoami ---------------------------------------------------------------


def test_whoami_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["whoami"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nick: notion-agent" in out
    assert "backend: colleague" in out
    assert "model:" in out


def test_whoami_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["whoami", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["nick"] == "notion-agent"
    assert payload["version"] == __version__
    assert payload["backend"] == "colleague"


# --- learn ----------------------------------------------------------------


def test_learn_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["learn"])
    assert rc == 0
    out = capsys.readouterr().out
    assert len(out) >= 200
    assert "notion-agent" in out
    assert "Exit-code policy" in out
    assert "--json" in out
    assert "explain" in out


def test_learn_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["learn", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "notion-agent"
    assert payload["version"] == __version__
    assert payload["json_support"] is True


# --- explain --------------------------------------------------------------


def test_explain_root(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain"])
    assert rc == 0
    assert "# notion-agent" in capsys.readouterr().out


def test_explain_self(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "notion-agent"])
    assert rc == 0
    assert capsys.readouterr().out.startswith("#")


def test_explain_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "whoami", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["path"] == ["whoami"]
    assert "notion-agent whoami" in payload["markdown"]


def test_explain_unknown_path_errors(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "nonexistent"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error:")
    assert "hint:" in captured.err


def test_every_catalog_path_resolves(capsys: pytest.CaptureFixture[str]) -> None:
    for path in known_paths():
        rc = main(["explain", *path])
        assert rc == 0, f"explain {' '.join(path)} failed"
        capsys.readouterr()


# Root aliases: catalog entries that name the tool itself rather than a verb, so
# they have no counterpart in the parser. Both console scripts are listed so
# `explain notion` and `explain notion-agent` each resolve.
_ROOT_ALIASES = {(), ("notion",), ("notion-agent",)}


def _registered_paths(
    parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()
) -> set[tuple[str, ...]]:
    """Collect every command path the parser actually registers, recursively.

    Walks the argparse subparser tree rather than the catalog, so this is an
    *independent* enumeration — that independence is the whole point (see
    :func:`test_every_registered_path_has_catalog_entry`).
    """
    paths: set[tuple[str, ...]] = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, subparser in action.choices.items():
                path = prefix + (name,)
                paths.add(path)
                paths |= _registered_paths(subparser, path)
    return paths


def test_every_registered_path_has_catalog_entry() -> None:
    """Every registered noun/verb must have an `explain` entry.

    `test_every_catalog_path_resolves` cannot catch a gap here: it iterates
    `known_paths()`, which is derived from the catalog itself, so a command
    registered but omitted from ENTRIES is simply never visited. This test
    enumerates the parser instead and compares, which is what makes the
    "a new verb without a catalog entry fails the suite" contract in CLAUDE.md
    true.
    """
    missing = _registered_paths(_build_parser()) - set(known_paths())
    assert not missing, "registered command(s) with no explain catalog entry: " + ", ".join(
        " ".join(p) for p in sorted(missing)
    )


def test_no_orphan_catalog_entries() -> None:
    """And no entry documents a command that no longer exists."""
    orphans = set(known_paths()) - _registered_paths(_build_parser()) - _ROOT_ALIASES
    assert not orphans, "catalog entr(ies) for unregistered command(s): " + ", ".join(
        " ".join(p) for p in sorted(orphans)
    )
