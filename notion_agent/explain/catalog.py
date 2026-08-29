"""Markdown catalog for ``notion-agent explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("notion-agent",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# notion-agent

A clonable template for AgentCulture mesh agents. It carries an agent-first CLI
(cited from the teken `python-cli` reference), a mesh identity (`culture.yaml` +
`CLAUDE.md`), the canonical guildmaster skill kit under `.claude/skills/`, and a
buildable/deployable package baseline. Clone it, rename the package, edit
`culture.yaml`, and you have a new agent.

## Verbs

- `notion-agent whoami` — identity probe from `culture.yaml`.
- `notion-agent learn` — structured self-teaching prompt.
- `notion-agent explain <path>` — markdown docs for any noun/verb.
- `notion-agent overview` — descriptive snapshot of the agent.
- `notion-agent doctor` — check the agent-identity invariants.
- `notion-agent cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `notion-agent explain whoami`
- `notion-agent explain doctor`
"""

_WHOAMI = """\
# notion-agent whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    notion-agent whoami
    notion-agent whoami --json
"""

_LEARN = """\
# notion-agent learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    notion-agent learn
    notion-agent learn --json
"""

_EXPLAIN = """\
# notion-agent explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    notion-agent explain notion-agent
    notion-agent explain whoami
    notion-agent explain --json <path>
"""

_OVERVIEW = """\
# notion-agent overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    notion-agent overview
    notion-agent overview --json
"""

_DOCTOR = """\
# notion-agent doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`colleague` → `AGENTS.colleague.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    notion-agent doctor
    notion-agent doctor --json
"""

_CLI = """\
# notion-agent cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    notion-agent cli overview
    notion-agent cli overview --json
"""


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("notion-agent",): _ROOT,
    ("notion",): _ROOT,
    ("whoami",): _WHOAMI,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
}
