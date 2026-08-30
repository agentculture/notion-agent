"""Markdown catalog for ``notion-agent explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("notion-agent",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# notion-agent

An agent-first CLI for controlling Notion — pages, databases (data sources),
blocks, comments and search — built for AgentCulture mesh agents. Every id
argument accepts a Notion id or URL; every verb supports `--json`; **every
write is dry-run by default and needs `--apply`** to be performed.

Auth: set `NOTION_API_KEY` (or `NOTION_TOKEN`) to an internal-integration or
personal access token. `notion-agent whoami` probes it and names the workspace.
Pages and databases must be shared with the integration (Notion → `...` →
Connections) or they are invisible to it.

## Nouns and verbs

- `notion-agent whoami` — identity + Notion auth probe (workspace, integration).
- `notion-agent search [query]` — find pages and data sources.
- `notion-agent page get|create|update|append|archive|restore`
- `notion-agent db get|query|row create|row update`
- `notion-agent block get|children|append|update|delete|restore`
- `notion-agent comment list|add`
- `notion-agent learn` / `explain <path>` / `overview` / `doctor` / `cli overview`
  — the agent-first introspection verbs.

## Exit-code policy

- `0` success
- `1` user-input error (bad id, unknown property, not shared with the integration)
- `2` environment / setup error (no token, token rejected, network, rate limit)
- `3+` reserved

## See also

- `notion-agent explain page` · `explain db` · `explain block` · `explain comment`
- `notion-agent explain whoami`
"""

_WHOAMI = """\
# notion-agent whoami

The smallest auth probe. Reports this agent's identity from `culture.yaml`
(nick, backend, model, version) and then calls Notion's `GET /users/me` to
name the workspace, the integration, where the token came from
(`NOTION_API_KEY` / `NOTION_TOKEN`) and the pinned API version.

Exits `2` with a hint when no token is set or Notion rejects it.

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


_SEARCH = """\
# notion-agent search

Search the pages and data sources shared with the integration. Read-only.

## Usage

    notion-agent search "roadmap"
    notion-agent search --data-sources            # only databases' data sources
    notion-agent search "plan" --pages --limit 5 --json
    notion-agent search --json --raw              # raw API objects

## Output

Text: one line per hit — `<object>\\t<id>\\t<title>\\t<url>`. JSON: a list of
`{object, id, title, url, parent, last_edited_time}`. Results are paginated
transparently up to `--limit` (default 20).
"""

_PAGE = """\
# notion-agent page

Pages: read one as Markdown, create, update properties, append content, or
move to / restore from the trash. Every id argument accepts a Notion id
(dashed or 32-hex) or a notion.so / app.notion.com URL.

**Writes are dry-run by default** — they print the request(s) they would send
and exit 0; add `--apply` to perform them.

## Verbs

- `page get <id>` — title, properties and body (as Markdown).
- `page create --parent <id> --title T [--body MD | --body-file F] [--set K=V]`
- `page update <id> [--title T] [--set K=V ...] [--icon EMOJI]`
- `page append <id> (--body MD | --body-file F) [--after BLOCK_ID]`
- `page archive <id>` / `page restore <id>` — trash / untrash (`in_trash`).

See `notion-agent explain page <verb>` for each.
"""

_PAGE_GET = """\
# notion-agent page get <id>

Fetch a page and render its content as Markdown. Read-only.

## Usage

    notion-agent page get <id-or-url>
    notion-agent page get <id> --json      # {id, title, url, parent, properties, markdown}
    notion-agent page get <id> --no-content     # properties only
    notion-agent page get <id> --depth 1        # nested blocks to fetch (default 3)
    notion-agent page get <id> --json --raw     # + raw page and block objects

A page that is not shared with the integration fails with exit 1 and a hint
naming the Connections menu.
"""

_PAGE_CREATE = """\
# notion-agent page create

Create a page under a parent page or as a row of a data source. Dry-run by
default; `--apply` performs the create.

## Usage

    notion-agent page create --parent <page-id> --title "Weekly notes" --body "# Hello"
    notion-agent page create --parent <data-source-id> --title "Task" --set "Status=Done" --apply
    cat notes.md | notion-agent page create --parent <id> --title T --body-file - --apply

`--parent` accepts a page, a data source, or a database with one data source.
`--set K=V` needs a data source parent (property values are typed from its
schema). Bodies longer than 100 blocks are created then appended in
follow-up requests; if a follow-up fails the error names the created page id
so you can resume with `page append`.
"""

_PAGE_UPDATE = """\
# notion-agent page update <id>

Change a page's title, typed properties (rows only) or icon. Only the given
properties are sent. Dry-run by default; `--apply` performs it.

## Usage

    notion-agent page update <id> --title "New title"
    notion-agent page update <row-id> --set "Status=Done" --set "Priority=High" --apply
"""

_PAGE_APPEND = """\
# notion-agent page append <id>

Append Markdown content to the end of a page (or after a given block).
Dry-run by default; `--apply` performs it. Blocks are sent in batches of 100.

## Usage

    notion-agent page append <id> --body "- new bullet"
    notion-agent page append <id> --body-file notes.md --apply
    notion-agent page append <id> --body "x" --after <block-id> --apply
"""

_PAGE_ARCHIVE = """\
# notion-agent page archive <id>

Move a page to Notion's trash (`in_trash: true`). Reversible with
`page restore`. Dry-run by default; `--apply` performs it.

## Usage

    notion-agent page archive <id>
    notion-agent page archive <id> --apply
"""

_PAGE_RESTORE = """\
# notion-agent page restore <id>

Restore a page from the trash (`in_trash: false`). Dry-run by default;
`--apply` performs it.

## Usage

    notion-agent page restore <id> --apply
"""

_DB = """\
# notion-agent db

Databases, addressed by their **data sources** (Notion API 2025-09-03+). Any
`<id>` may be a data source id, or a database id that resolves to its single
data source (a database with several fails, listing them).

## Verbs

- `db create --parent <page-id> --title T --prop "Name=type[:opts]"` — new database.
- `db get <id>` — the property schema (names, types, options).
- `db query <id> [--where "Prop=value"] [--filter JSON] [--sort Prop:desc] [--limit N]`
- `db row create <id> --title T --set K=V ...` — add a row (dry-run by default).
- `db row update <page-id> --set K=V ...` — change a row's properties.

See `notion-agent explain db <verb>` for each.
"""

_DB_CREATE = """\
# notion-agent db create

Create a database (and its single data source) under a parent page. Dry-run
by default; `--apply` performs it. Properties are `Name=type[:options]`; a
`Name` title property is added when you give none.

## Usage

    notion-agent db create --parent <page-id> --title "Agents db" \\
        --prop "Name=title" --prop "Kind=select:agent,human" --prop "Active=checkbox" \\
        --prop "Tags=multi_select:core,infra" --prop "Since=date" --prop "Home=url"
    notion-agent db create --parent <page-id> --title "Links" \\
        --prop "Rel=relation:<data-source-id>" --apply

Types: title, rich_text, number[:format], select[:a,b], multi_select[:a,b],
status, checkbox, date, url, email, phone_number, people, files,
relation:<data-source-id>. The result names the new data source id — pass it
to `db row create` / `db query`.
"""

_DB_GET = """\
# notion-agent db get <id>

Show a data source's schema: each property's name, type, options and whether
it is writable. Read-only.

## Usage

    notion-agent db get <data-source-or-database-id>
    notion-agent db get <id> --json
"""

_DB_QUERY = """\
# notion-agent db query <id>

Query rows. `--where` builds an AND filter from the schema (select/status →
equals, multi_select/title/text → contains, checkbox/number/date → equals);
`--filter` takes raw Notion filter JSON. Read-only.

## Usage

    notion-agent db query <id> --where "Status=In progress" --sort "Priority:desc"
    notion-agent db query <id> --filter '{"property":"Done","checkbox":{"equals":false}}' --json
    notion-agent db query <id> --limit 200 --json

Text: `<id>\\t<title>\\t<Prop=value ...>` per row. JSON: a list of
`{id, url, title, properties}` with flattened values (`--raw` for the API shape).
"""

_DB_ROW = """\
# notion-agent db row

Row-level writes: `db row create <data-source-id> --title T --set K=V ...` and
`db row update <page-id> --set K=V ...`. Both are dry-run by default; `--apply`
performs them. Value syntax: comma-separated for multi_select / people /
relation; `start/end` for date ranges; true/false for checkboxes.
"""

_DB_ROW_CREATE = """\
# notion-agent db row create <id>

Add a row to a data source. Property values are typed from the schema.
Dry-run by default; `--apply` performs it.

## Usage

    notion-agent db row create <id> --title "Ship v1" --set "Status=Todo" --set "Team=Core,Infra"
    notion-agent db row create <id> --title T --body "# Notes" --apply
"""

_DB_ROW_UPDATE = """\
# notion-agent db row update <page-id>

Change a row's properties (only the given ones are sent). Dry-run by default;
`--apply` performs it.

## Usage

    notion-agent db row update <page-id> --set "Status=Done" --apply
"""

_BLOCK = """\
# notion-agent block

Individual blocks: read one, list children as Markdown, append after a block,
edit a block's text, trash / restore. Writes are dry-run by default;
`--apply` performs them.

## Verbs

- `block get <id>` / `block children <id> [--depth N]`
- `block append <id> (--body MD | --body-file F) [--after BLOCK_ID]`
- `block update <id> --text "new markdown line"`
- `block delete <id>` (to trash) / `block restore <id>`
"""

_BLOCK_GET = """\
# notion-agent block get <id>

Fetch one block: type, parent, has_children and its Markdown rendering.
Read-only.

## Usage

    notion-agent block get <id>
    notion-agent block get <id> --json
"""

_BLOCK_CHILDREN = """\
# notion-agent block children <id>

Render a block's (or page's) children as Markdown, recursing `--depth` levels
(default 3). Read-only.

## Usage

    notion-agent block children <page-or-block-id>
    notion-agent block children <id> --depth 1 --json
"""

_BLOCK_APPEND = """\
# notion-agent block append <id>

Append Markdown as children of a block (or page), optionally positioned after
a sibling. Dry-run by default; `--apply` performs it.

## Usage

    notion-agent block append <id> --body "- item" --after <sibling-id> --apply
"""

_BLOCK_UPDATE = """\
# notion-agent block update <id>

Replace a text block's rich text with one line of Markdown, keeping its type.
Refuses blocks without text (dividers, images, child pages). Dry-run by
default; `--apply` performs it.

## Usage

    notion-agent block update <id> --text "**done** — see notes" --apply
"""

_BLOCK_DELETE = """\
# notion-agent block delete <id>

Move a block to the trash (Notion's DELETE is a trash, not a hard delete).
Reversible with `block restore`. Dry-run by default; `--apply` performs it.

## Usage

    notion-agent block delete <id> --apply
"""

_BLOCK_RESTORE = """\
# notion-agent block restore <id>

Restore a trashed block (`in_trash: false`). Dry-run by default; `--apply`
performs it.

## Usage

    notion-agent block restore <id> --apply
"""

_COMMENT = """\
# notion-agent comment

Comments on pages: list them, or add one (to the page or to an existing
discussion thread). `comment add` is dry-run by default; `--apply` posts.

## Verbs

- `comment list <page-or-block-id> [--limit N]`
- `comment add <page-id> --body TEXT [--discussion DISCUSSION_ID]`
"""

_COMMENT_LIST = """\
# notion-agent comment list <id>

List comments on a page or block. Read-only.

## Usage

    notion-agent comment list <page-id>
    notion-agent comment list <page-id> --json   # [{id, discussion_id, created_time, author, text}]
"""

_COMMENT_ADD = """\
# notion-agent comment add <page-id>

Add a comment to a page, or reply in a discussion thread. Dry-run by default;
`--apply` posts it.

## Usage

    notion-agent comment add <page-id> --body "Reviewed, looks good" --apply
    notion-agent comment add <page-id> --body "+1" --discussion <discussion-id> --apply
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
    ("search",): _SEARCH,
    ("page",): _PAGE,
    ("page", "get"): _PAGE_GET,
    ("page", "create"): _PAGE_CREATE,
    ("page", "update"): _PAGE_UPDATE,
    ("page", "append"): _PAGE_APPEND,
    ("page", "archive"): _PAGE_ARCHIVE,
    ("page", "restore"): _PAGE_RESTORE,
    ("db",): _DB,
    ("db", "create"): _DB_CREATE,
    ("db", "get"): _DB_GET,
    ("db", "query"): _DB_QUERY,
    ("db", "row"): _DB_ROW,
    ("db", "row", "create"): _DB_ROW_CREATE,
    ("db", "row", "update"): _DB_ROW_UPDATE,
    ("block",): _BLOCK,
    ("block", "get"): _BLOCK_GET,
    ("block", "children"): _BLOCK_CHILDREN,
    ("block", "append"): _BLOCK_APPEND,
    ("block", "update"): _BLOCK_UPDATE,
    ("block", "delete"): _BLOCK_DELETE,
    ("block", "restore"): _BLOCK_RESTORE,
    ("comment",): _COMMENT,
    ("comment", "list"): _COMMENT_LIST,
    ("comment", "add"): _COMMENT_ADD,
}
