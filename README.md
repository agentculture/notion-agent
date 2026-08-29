# notion-agent

Agent-first CLI for controlling Notion: pages, databases, blocks, and search.
Also a communication lane — other AgentCulture agents use their own CLIs and
skills to talk to each other through shared Notion pages and databases.

> **Status: early scaffold.** The Notion surface described above is the goal,
> not yet the code. What ships today is the agent-first CLI baseline — the
> introspection verbs, the mesh identity, the skill kit, and the CI/deploy
> wiring — with **no Notion client, auth, or nouns** yet. See
> [Roadmap](#roadmap) and [`CLAUDE.md`](CLAUDE.md) for what exists on disk.

## What you get

- **An agent-first CLI** cited from [teken](https://github.com/agentculture/teken)
  (`afi-cli`) — the runtime package has no third-party dependencies.
- **A mesh identity** — `culture.yaml` (`suffix` + `backend`) and the matching
  resident prompt file (`AGENTS.colleague.md`, since this agent runs
  `backend: colleague`).
- **The canonical guildmaster skill kit** under `.claude/skills/`, vendored
  cite-don't-import. See [`docs/skill-sources.md`](docs/skill-sources.md).
- **A build + deploy baseline** — pytest, lint, the agent-first rubric gate, and
  PyPI Trusted Publishing wired into GitHub Actions.

## Quickstart

```bash
uv sync
uv run pytest -n auto                 # run the test suite
uv run notion whoami                  # identity from culture.yaml
uv run notion learn                   # self-teaching prompt (add --json)
uv run teken cli doctor . --strict    # the agent-first rubric gate CI runs
```

The package installs **two console scripts** for the same entry point:
`notion` (short, primary) and `notion-agent`. `python -m notion_agent` works too.

## CLI

| Verb | What it does |
|------|--------------|
| `whoami` | Report this agent's nick, version, backend, and model from `culture.yaml`. |
| `learn` | Print a structured self-teaching prompt. |
| `explain <path>` | Markdown docs for any noun/verb path. |
| `overview` | Read-only descriptive snapshot of the agent. |
| `doctor` | Check the agent-identity invariants (prompt-file-present, backend-consistency). |
| `cli overview` | Describe the CLI surface itself. |

Every command supports `--json`. Results go to stdout, errors/diagnostics to
stderr (never mixed). Exit codes: `0` success, `1` user error, `2` environment
error, `3+` reserved.

Because the Notion surface isn't built yet, `learn` and `explain` still describe
this repo as the mesh-agent template it was scaffolded from.

## Roadmap

The Notion capability is not implemented. When it lands, expect noun groups
under `notion_agent/cli/_commands/` — `page`, `database`, `block`, `search` —
each following the existing `register(sub)` pattern with a matching `explain`
catalog entry, `--json` on every verb, and structured `CliError` failures, plus
a Notion client dependency and token-from-environment auth.

## Development

```bash
uv run pytest -n auto                       # tests
uv run black --check notion_agent tests     # lint gates CI runs
uv run isort --check-only notion_agent tests
uv run flake8 notion_agent tests
uv run bandit -c pyproject.toml -r notion_agent
```

Every PR bumps the version (the `version-check` CI job enforces it) and goes
through the `cicd` skill. Pushing to `main` publishes to PyPI via Trusted
Publishing. See [`CLAUDE.md`](CLAUDE.md) for the full conventions — architecture,
the stable-contract modules, worktree layout, and the vendored-skill rules.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
