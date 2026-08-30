# notion-agent

Agent-first CLI for controlling Notion — pages, databases, blocks, comments,
and search — built for AgentCulture mesh agents. Every id argument accepts a
Notion id or URL, every verb speaks `--json`, and **every write is a dry run
until you pass `--apply`**.

It is also the seed of a **communication lane**: other AgentCulture agents will
use their own CLIs and skills to talk to each other *through* shared Notion
pages and databases. That lane (surface 2 in
[issue #1](https://github.com/agentculture/notion-agent/issues/1)) is not built
yet — see [Roadmap](#roadmap).

> Notion is a trademark of Notion Labs, Inc. This is an unofficial community
> CLI, not affiliated with or endorsed by Notion.

## Where Notion sits among the mesh's lanes

| Substrate | Shape | Lane |
|-----------|-------|------|
| `culture` (IRC mesh) | live conversation, ephemeral | agents talking *now* |
| `events-cli` (MQTT) | fire-and-forget events, transport-independent | machine signals |
| **`notion-agent`** | durable documents + database rows, **human-visible** | documents, tables, statuses a human reads too |

The distinguishing property is **durability + human co-presence**: a person
opens Notion and reads the same thing the agents wrote, in a shape they already
use. Notion has no push, so there is **no real-time** here — a consumer that
needs promptness polls; anything that needs sub-second delivery belongs in one
of the other two lanes. (Decision 4 in [`docs/decisions.md`](docs/decisions.md).)

## Quickstart

```bash
uv sync
export NOTION_API_KEY=ntn_...            # internal integration or personal access token
uv run notion whoami                     # proves the token; names the workspace + integration
uv run notion search "roadmap"           # pages + data sources shared with the integration
uv run notion page get <id-or-url>       # a page rendered as Markdown
uv run notion page create --parent <id> --title "Notes" --body "# Hello"          # dry run
uv run notion page create --parent <id> --title "Notes" --body "# Hello" --apply  # for real
uv run notion learn                      # the self-teaching prompt (add --json)
```

Pages and databases are invisible to the API until they are **shared with the
integration** (Notion → `...` → Connections). The CLI turns that 404 into a
clear *"not shared with the integration 'Spark'"* error with a hint.

The package installs **two console scripts** for the same entry point:
`notion` (short, primary) and `notion-agent`. `python -m notion_agent` works
too. The runtime has **no third-party dependencies** — the client is `urllib`.

## CLI

| Verb | What it does |
|------|--------------|
| `whoami` | Identity from `culture.yaml` **plus the Notion auth probe**: workspace, integration, token source, API version. Exit `2` when no token is set. |
| `search [query] [--pages\|--data-sources]` | Find pages and data sources. |
| `page get <id>` | Title, properties, and body as Markdown. |
| `page create --parent <id> --title T [--body MD\|--body-file F] [--set K=V]` | New page under a page, or a row under a data source. |
| `page update <id> [--title T] [--set K=V] [--icon E]` | Change only the given properties. |
| `page append <id> --body MD [--after BLOCK]` | Append Markdown as blocks. |
| `page archive <id>` / `page restore <id>` | Trash / untrash (`in_trash`). |
| `db get <id>` | A data source's property schema. |
| `db query <id> [--where "Prop=v"] [--filter JSON] [--sort Prop:desc]` | Rows, flattened. |
| `db row create <id> --title T --set K=V` / `db row update <page-id> --set K=V` | Typed row writes. |
| `block get\|children\|append\|update\|delete\|restore` | Individual blocks. |
| `comment list <id>` / `comment add <page-id> --body TEXT` | Page comments. |
| `learn` / `explain <path>` / `overview` / `doctor` / `cli overview` | Agent-first introspection. |

Every write verb prints the request(s) it would send and exits `0` unless
`--apply` is given. `db` verbs address **data sources** (Notion API
2025-09-03+); a database id is accepted and resolved when it has one data
source. Page bodies are Markdown both ways — headings, paragraphs, nested
lists, to-dos, quotes, fenced code, dividers, and inline marks round-trip;
other block types render as labelled placeholders. `notion explain <noun>
<verb>` documents each verb.

Results go to stdout, errors/diagnostics to stderr (never mixed). Exit codes:
`0` success, `1` user error (bad id, unknown property, not shared), `2`
environment error (no token, token rejected, network, rate limit), `3+`
reserved. Every error carries Notion's `request_id`.

## Auth and safety

- Token: `NOTION_API_KEY`, falling back to `NOTION_TOKEN`. Nothing else is
  read; no workspace or page id is hardcoded.
- The API version is pinned to `2026-03-11` in the client (`NOTION_VERSION`
  overrides it, at your own risk).
- Rate limiting (~3 req/s) and pagination are handled in the client. `429` is
  retried for every method; `5xx` only for `GET`, so a write is never replayed
  into a duplicate.
- The token never appears in output — dry-run plans show method, path, and
  body only.

## Development

```bash
uv run pytest -n auto                       # tests (fake transport — no network)
uv run black --check notion_agent tests     # lint gates CI runs
uv run isort --check-only notion_agent tests
uv run flake8 notion_agent tests
uv run bandit -c pyproject.toml -r notion_agent
uv run teken cli doctor . --strict          # the agent-first rubric gate
```

Every PR bumps the version (the `version-check` CI job enforces it) and goes
through the `cicd` skill. Pushing to `main` publishes to PyPI via Trusted
Publishing. See [`CLAUDE.md`](CLAUDE.md) for the architecture, the
stable-contract modules, worktree layout, and the vendored-skill rules, and
[`docs/decisions.md`](docs/decisions.md) for the decisions behind the design.

## Roadmap

**Surface 2 — the communication lane.** A versioned Notion database schema
(sender, recipient/channel, timestamp, kind, status, body), `notion lane init`
to provision it (dry-run by default), send / receive / mark-handled verbs
usable from another agent's shell, and a vendorable `.claude/skills/` skill
that shells out to `notion`. It builds on the contracts shipped here — ids,
Markdown bodies, dry-run writes, data-source addressing — and is tracked in
the follow-up issue linked from issue #1.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
