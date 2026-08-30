# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`notion-agent` is an **agent-first CLI for controlling Notion** — pages,
databases, blocks, and search — and a **communication lane**: other AgentCulture
agents use their own CLIs and skills to talk to each other through shared Notion
pages and databases.

**Status: surface 1 (the control CLI) is built; surface 2 (the lane) is not.**
`whoami` is the auth probe, and `search`, `page`, `db`, `block`, `comment` are
real noun groups under `cli/_commands/` on top of a zero-dependency client in
`notion_agent/notion/`. The communication lane (schema, `lane init`,
send/receive, the vendorable skill) is the roadmap — see `## Roadmap` and the
follow-up issue linked from issue #1. Design decisions and their reasoning are
in `docs/decisions.md`; the devague spec and plan that produced this surface
are in `docs/specs/` and `docs/plans/`.

It is a sibling to [`guildmaster`](https://github.com/agentculture/guildmaster)
(the **skills supplier**), [`steward`](https://github.com/agentculture/steward)
(**alignment** — `steward doctor`, the sibling-pattern baseline), and
[`teken`](https://github.com/agentculture/teken) (the **afi-cli** "Agent First
Interface" scaffolder this CLI is cited from) within the Organic Development
framework.

## Commands

```bash
uv sync                                    # create .venv, install dev deps
uv run pytest -n auto                      # full suite (xdist, parallel)
uv run pytest tests/test_cli.py::test_whoami_json -v   # a single test
uv run pytest --cov=notion_agent --cov-report=term     # coverage (fails under 60%)

uv run notion whoami                       # or: uv run notion-agent whoami
uv run notion learn --json

uv run black --check notion_agent tests    # the four lint gates CI runs
uv run isort --check-only notion_agent tests
uv run flake8 notion_agent tests
uv run bandit -c pyproject.toml -r notion_agent
markdownlint-cli2 "**/*.md" "#node_modules" "#.local" "#.claude/skills"
uv run teken cli doctor . --strict         # the agent-first rubric gate
```

`black`/`isort`/`flake8` all agree on **line length 100**. The `run-tests` skill
wraps the pytest invocation; `sonarclaude` queries the SonarCloud project
`agentculture_notion-agent`.

## The CLI

The CLI is cited (cite-don't-import) from teken's `python-cli` reference
(`teken cli cite`), and the **runtime package has no third-party dependencies** —
the Notion client is `urllib` (`notion_agent/notion/client.py`), a deliberate
choice so a mesh install stays weightless; `teken` is a dev dependency only.

Two console scripts point at the same entry point: **`notion`** (short, primary)
and **`notion-agent`** (matches the argparse `prog`, the `explain` catalog, the
tests, and every doc string, so commands copied out of `learn` output run as
written). `python -m notion_agent` works too.

### Architecture

Everything hangs off `notion_agent/cli/__init__.py:main`:

- **`_build_parser()`** builds the root parser, then calls a `register(sub)`
  function per command module in `cli/_commands/`. **This is the extension
  point** — a new noun group is a new module with a `register(sub)` and one line
  in `_build_parser()` (there is a commented placeholder showing the shape).
  Each `register()` adds its own `--json` flag and a `func` default.
- **`_dispatch(args)`** calls `args.func(args)` and is the *only* place
  exceptions become exit codes. A handler returns `None` or an `int`; failures
  raise `CliError`. Any other exception is caught and wrapped into a `CliError`
  so **no Python traceback ever reaches stderr** — that is a contract the rubric
  checks, not a nicety.
- **`_CliArgumentParser`** overrides argparse's `.error()` so parse-time failures
  (unknown verb, missing arg) render in the same `error:` / `hint:` shape and
  exit `1` instead of argparse's bare exit `2`. Because parse errors happen
  *before* `args.json` exists, `main()` scans raw argv for `--json` and stashes
  the answer in the class-level `_json_hint`. It is passed as `parser_class=` to
  every `add_subparsers()` call so the behavior propagates — **a noun group that
  builds subparsers without `parser_class=type(p)` silently loses the structured
  error contract** (see `_commands/cli.py` for the correct pattern).

Three modules are marked **stable-contract** in their docstrings — change them
only deliberately:

- **`cli/_errors.py`** — `CliError{code, message, remediation}` and the exit-code
  policy: `0` success, `1` user-input error, `2` environment/setup error, `3+`
  reserved.
- **`cli/_output.py`** — **results to stdout, errors and diagnostics to stderr,
  never mixed**, in both text and JSON mode. Text-mode errors render as
  `error: <message>` + `hint: <remediation>`; the `hint:` prefix is required by
  the rubric.
- **`explain/`** — `catalog.py` maps command-path tuples to verbatim markdown;
  `resolve()` raises `CliError` on an unknown path. **Every registered noun/verb
  needs a catalog entry**, and that is enforced in both directions:
  `test_every_registered_path_has_catalog_entry` walks the *parser's* subparser
  tree and diffs it against the catalog, so a new verb without an entry fails the
  suite; `test_no_orphan_catalog_entries` catches the reverse (minus the root
  aliases `()`, `notion`, `notion-agent`, which name the tool, not a verb). Note
  `test_every_catalog_path_resolves` proves only that entries *render* — it
  iterates `known_paths()`, which comes from the catalog itself, so it can never
  notice a missing one.

`whoami.py` carries two helpers the rest of the CLI reuses: `find_culture_yaml()`
walks up from `__file__` (deliberately **not** the CWD — the identity must be
this agent's own, and a wheel install finds nothing and falls back to literal
defaults), and `read_agent_fields()` parses `culture.yaml` **without a YAML
dependency** to keep `dependencies = []` true. It handles the documented
`suffix`/`backend`/`model` shape only and falls back to defaults on anything
fancier. `doctor.py` builds on both. `whoami` is also the **Notion auth probe**:
after the identity block it calls `GET /users/me` and reports workspace,
integration, token source and API version; with no token it exits `2`.

### The Notion surface

- **`notion_agent/notion/`** is the client layer, shared by every noun:
  `client.py` (auth from `NOTION_API_KEY` → `NOTION_TOKEN`, injectable;
  `Notion-Version: 2026-03-11`; ~3 req/s throttle; `429` retried for any
  method, `5xx` only for `GET`; `paginate()`; `NotionError` with `request_id`),
  `ids.py` (ids/URLs → dashed UUID), `markdown.py` (**Markdown ⇄ blocks as pure
  functions** — verbs never build block JSON by hand; `tests/test_markdown.py`
  holds the round-trip guard), `props.py` (flatten property values for reading,
  build typed payloads from `Name=value` for writing).
- **`cli/_commands/_common.py`** is what a noun module uses: `get_client()`,
  `notion_command` (wraps a handler so `NotionError`/`ValueError` become
  `CliError`), `to_cli_error` (the one place Notion errors are mapped — `404
  object_not_found` becomes *"not shared with the integration NAME"*,
  `401` is exit `2`), and the **dry-run contract**: a write verb builds a
  `Plan` of `method/path/body` steps and either `emit_plan`s it (default,
  exit `0`, nothing sent) or `run_plan`s it under `--apply`. Plans never
  include headers, so the token cannot leak into output. Tests inject a fake
  transport by monkeypatching `_common.build_client`
  (`tests/fake_notion.py` — note `.on()` replaces an existing route, so
  `.standard().on(...)` overrides).
- **API version semantics you must keep:** databases expose `data_sources[]`
  and are queried via `POST /data_sources/{id}/query` (`db` verbs take either
  id and resolve through `_common.resolve_data_source`); trash is `in_trash`
  (never `archived`); append positioning is `position.after_block` (never
  `after`); search filters are `page` / `data_source`.

Descriptive verbs must never hard-fail on a bad path — `overview` takes an
optional `target` positional that it accepts and ignores, so `overview
/no/such/path` still exits `0`. There is a test for it.

## Identity

Declared in `culture.yaml`:

```yaml
agents:
- suffix: notion-agent
  backend: colleague
  model: sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP
```

`backend: colleague` fixes the resident prompt file to **`AGENTS.colleague.md`**
— the mesh runtime reads that file, while `CLAUDE.md` (this file) stays the
Claude Code guidance file. Together they satisfy the two invariants `steward
doctor` verifies: **prompt-file-present** and **backend-consistency**. `notion
doctor` checks the same invariants locally (plus a skills-present warning) and
exits `1` when unhealthy.

Note the model pin is inherited from the scaffold and predates the lobes gateway
drop of Qwen3.6 (see `CHANGELOG.md` 0.7.0) — verify it resolves before relying on
a colleague run.

## Skills

`.claude/skills/` vendors the **canonical guildmaster skill kit**
(cite-don't-import). Provenance, per-skill sync dates, and the re-sync procedure
live in `docs/skill-sources.md` — read it before touching anything under
`.claude/skills/`. Several skills are **tracked local divergences** vendored
directly from their origin rather than guildmaster (`ask-colleague` from
`colleague`; `scope` / `challenge` / `deviate` / `summarize-delivery` from
`devague`), and the `agex` → `devex` rename was patched in place. That ledger is
what keeps a re-sync from silently reverting those.

**Vendored means vendored.** Findings raised against a vendored script — bot or
human — are fixed **upstream and pulled back in**, never patched here; a local
patch is exactly the drift the ledger exists to prevent. Every vendored
`SKILL.md` carries `type: command`, which is load-bearing: `core.skill_loader`
silently skips any `SKILL.md` lacking it.

Tooling prerequisites: **`devex`** (>=0.21) on PATH (the `cicd` skill delegates
the PR lifecycle to `devex pr`) and **`agtag`** (>=0.1) on PATH (the
`communicate` skill wraps `agtag issue`). **`colleague`** on PATH is *optional* —
only `ask-colleague` needs it, and only when invoked.

Per-machine paths (the Culture server manifest, sibling project locations) go in
a git-ignored `skills.local.yaml`; copy `.claude/skills.local.yaml.example`.

## Conventions

- **Reach for `ask-colleague` reflexively.** Treat it (the `colleague` CLI) as
  the teammate at the next desk, not a last resort — its value is a *second,
  independent mind* (a different backend/model), not a stronger one. Before
  presenting or opening a PR on a non-trivial committed diff, run `review`; for a
  fresh read of an unfamiliar area whose answer is independent of your current
  context, run `explore`. Both are **read-only** (isolated in a throwaway
  worktree, zero side effects), so the reflex is always safe. The side-effecting
  `write --apply` / `write --pr` still needs the user's go-ahead. Colleague's
  output is a second opinion to verify and own, never authority.
- **Every PR bumps the version** — even docs/config/CI. Use the `version-bump`
  skill; the `version-check` CI job comments on the PR and blocks merge
  otherwise. It runs on `pull_request` events only, by design.
- **PRs** go through the `cicd` skill (`devex pr` + SonarCloud gating; `await` is
  the "wake me when this is triage-able" verb). Sign online posts as
  `- notion-agent (Claude)` — the `cicd` / `communicate` scripts resolve the nick
  from `culture.yaml` automatically, so don't hand-sign inside a body they author.
- **Deploy**: pushing to `main` publishes to PyPI via Trusted Publishing
  (`.github/workflows/publish.yml`); PRs from this repo do a TestPyPI dry-run at
  `<version>.dev<run-number>`. Both jobs are path-filtered to `pyproject.toml`
  and `notion_agent/**`, and the TestPyPI job is skipped on fork PRs (no OIDC).
  The `pypi` / `testpypi` GitHub environments and a PyPI Trusted Publisher must
  be configured before either can succeed.
- **SonarCloud** gates CI (`sonar.qualitygate.wait=true`), but only when
  `SONAR_TOKEN` is present — the scan step is guarded by `if: env.SONAR_TOKEN !=
  ''`, so token-less repos and fork PRs stay green. Coverage uses
  `relative_files = true` so `coverage.xml` paths map onto `sonar.sources`.

This file describes the repository **as it exists on disk today**. When you edit,
keep claims grounded in checked-in reality; if a section drifts ahead of reality,
mark it `(planned)` or move it under a `## Roadmap` heading.

## Git worktrees

**Worktrees you create live in `../.worktrees.notion-agent/<name>/`** — one
repo-named directory beside the checkout, one subfolder per worktree:

```bash
git worktree add ../.worktrees.notion-agent/<name> -b <branch>
```

Do **not** use a shared `../worktrees/` directory. This workspace holds many
sibling projects, and a generic shared folder accumulates orphaned trees from
several repos at once with nothing indicating who owns which — someone clearing
stale trees cannot tell yours from junk. Use a branch prefix scoped to the work
(`notion/pages`, not `agent/t2`): plain `agent/*` names collide with leftovers
from earlier fan-outs and `git worktree add -b` fails on an existing branch.

**Following the vendored `assign-to-workforce` skill:** its fan-out example uses
both the shared `../worktrees/` path and `agent/<task-id>` branch names — the two
things above say not to. That skill is cited verbatim and must not be edited, so
override *both* when you follow it.

**Exception — tool-managed throwaways.** `ask-colleague`'s read-only verbs create
a detached worktree under `${TMPDIR:-/tmp}` and delete it on an EXIT trap. The
tree never outlives the command, so it is outside this rule. Expect `git worktree
list` to show one while such a command is in flight.

Remove a worktree with `git worktree remove <path>`, which deletes the directory
and its bookkeeping together. `git worktree prune` only clears metadata for
directories that are *already* gone. Never `rm -rf` a worktree you did not create.

## Memory — recall before, remember after

This repo keeps its eidetic memory **in-repo and public**: records resolve to
`<repo-root>/.eidetic/memory` — committed, and shared with the team and mesh
peers (the `claude` and `colleague` backends both resolve the `notion-agent`
scope), so memory travels with the repo rather than a private home-dir store.

- **`/recall` before you start** a non-trivial task — prior decisions, gotchas,
  "have we done this before?" — so you build on what's known instead of
  re-deriving it.
- **`/remember` when something worth keeping surfaces** — a non-obvious decision
  and its rationale, a constraint, a fix and *why*, a gotcha that cost time.
  Capture it as it happens.

A plain `/remember` lands in `./.eidetic/memory` (the wrappers here override
eidetic's upstream private default to `--visibility public`; in-repo routing
needs `eidetic >= 0.10.0`). Keep something out of the committed store with
`--visibility private` (routes to `$HOME`, never committed); `/recall` reads both
and merges. Don't store what the repo already records — store what you'd have to
re-derive.

## Layout

```text
notion_agent/             agent-first CLI (cited from teken's python-cli reference)
  cli/__init__.py         parser, register() wiring, _dispatch exception->exit-code
  cli/_errors.py          CliError + exit-code policy      (stable-contract)
  cli/_output.py          stdout/stderr split, JSON mode    (stable-contract)
  cli/_commands/          one module per noun/verb, each with register(sub)
    _common.py            get_client, NotionError->CliError, the dry-run Plan contract
    search.py page.py db.py block.py comment.py   the Notion nouns
    whoami.py             identity + Notion auth probe
  notion/                 zero-dep client layer: client, ids, markdown, props
  explain/catalog.py      markdown keyed by command-path tuple (stable-contract)
tests/                    pytest; fake_notion.py is the recorded-shape fake transport
docs/decisions.md         issue #1's parked unknowns, decided with reasoning
docs/specs/ docs/plans/   the devague frame + plan that produced surface 1
.claude/skills/           vendored guildmaster skill kit (cite-don't-import)
docs/skill-sources.md     skill provenance ledger
culture.yaml              mesh identity (suffix + backend)
.github/workflows/        tests + lint + version-check; PyPI Trusted Publishing
```

## Roadmap — surface 2, the communication lane

Not built. Expect a versioned lane schema (a Notion database whose properties
are the message contract), `notion lane init` to provision it (dry-run by
default), send / receive / mark-handled verbs usable from another agent's
shell (polling with a cursor or status filter — Notion has no push), and a
vendorable `.claude/skills/<name>/` skill that shells out to `notion`. It
builds on the contracts shipped in surface 1 — ids, Markdown bodies, dry-run
writes, data-source addressing — rather than re-deciding them. `block update`
is last-writer-wins, so the lane must not rely on in-place edits for state
that several agents write.
