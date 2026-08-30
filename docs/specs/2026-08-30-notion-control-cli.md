# notion control CLI

> notion-agent controls a Notion workspace from an agent-first CLI: search, page, db, block, comment nouns, dry-run-by-default writes, Markdown<->blocks, zero-dep urllib client with pagination + rate limiting, whoami as the auth probe
> instruction: verify with: uv run pytest -n auto; uv run teken cli doctor . --strict; uv run notion whoami; uv run notion page get <url>

## Audience

- AgentCulture mesh agents driving Notion from a shell (and the humans who read what they write in Notion)

## Before → After

- Before: the repo is the renamed culture-agent-template: six introspection verbs, no Notion client, no auth, dependencies=\[\]
- After: an agent runs 'notion whoami' to prove its token, 'notion search', 'notion page get <id-or-url>' to read a page as Markdown, and creates/updates/appends pages, rows, blocks and comments — every write printing a dry-run plan unless --apply is passed

## Why it matters

- surface 2 (the durable, human-visible communication lane) can only be built on a control CLI whose verbs, ids, text representation and dry-run semantics are already settled

## Requirements

- new noun modules search/page/db/block/comment under `notion_agent`/cli/`_commands`/ each with register(sub), `parser_class`=type(p), --json, CliError — per CLAUDE.md architecture + tests/`test_cli.py` catalog-coverage tests
  - honesty: main(\['<noun>','<verb>','--bogus'\]) exits 1 with error:/hint: on stderr for every new noun (`parser_class` propagated)
- every new verb gets an explain catalog entry — `test_every_registered_path_has_catalog_entry` / `test_no_orphan_catalog_entries` diff the parser tree against ENTRIES
  - honesty: `test_every_registered_path_has_catalog_entry` and `test_no_orphan_catalog_entries` pass with the new nouns registered
- every write verb (page create/update/append/archive/restore, db row create/update, block append/update/delete, comment add) is dry-run by default and prints the planned request(s) to stdout with exit 0; --apply performs it (issue #1 'no exceptions')
  - honesty: a test drives each write verb through a fake transport and asserts zero mutating requests were sent without --apply and exactly the expected ones with it
- whoami keeps the culture.yaml identity block and adds the Notion auth probe (workspace, integration, token source, API version); a missing token exits `EXIT_ENV_ERROR` (2) with a hint naming `NOTION_API_KEY`
  - honesty: main(\['whoami'\]) with `NOTION_API_KEY` unset exits 2 and stderr contains '`NOTION_API_KEY`'; with a fake transport returning users/me it prints the workspace name
- `object_not_found` (404) surfaces as a first-class 'not shared with the integration <name>' error with remediation, not a bare 404 (issue #1 parked unknown 3)
  - honesty: a fake 404 `object_not_found` response yields exit 1 with 'shared' and the integration name in the hint
- Markdown<->blocks lives in `notion_agent`/notion/markdown.py as pure functions with a md->blocks->md round-trip test; verbs never build block JSON by hand
  - honesty: `blocks_to_markdown`(`markdown_to_blocks`(sample)) == sample for a canonical sample covering headings, paragraphs, nested lists, to-dos, quote, code, divider and inline marks
- pagination (`has_more`/`next_cursor`) and rate limiting (~3 rps throttle + Retry-After-honouring 429/5xx retry) are centralised in NotionClient; no verb re-implements either
  - honesty: a fake transport returning `has_more` pages yields all items from client.paginate; a 429 with Retry-After is retried and the sleep is called with at least that many seconds
- learn and overview enumerate the new nouns — their verb lists are hand-maintained strings in learn.py/overview.py (not derived from the parser), so a test asserts every top-level registered noun is named in 'learn' output
  - honesty: a test walks `_build_parser`'s top-level subparsers and asserts each noun name appears in main(\['learn'\]) stdout
- retries never duplicate writes: 429 responses are retried for every method (the server did not process the request), but 5xx responses are retried only for GET — a write that got a 5xx is reported with its `request_id` rather than replayed
  - honesty: fake transport: a POST answered 503 is NOT retried and raises; a GET answered 503 then 200 succeeds; a POST answered 429 then 200 succeeds
- a page create whose body exceeds 100 blocks is one create plus follow-up appends; if a follow-up fails, the error names the created page id so the agent can resume with 'page append' instead of re-creating
  - honesty: fake transport: page create with 150 blocks issues 1 POST /pages + 1 PATCH /blocks/{id}/children; when the PATCH fails, the error message contains the new page id
- every failed API call surfaces Notion's `request_id` in the error message so a support/log trail exists (observability), in both text and --json error output
  - honesty: fake transport 404 with `request_id` 'req-123' → stderr (text and --json) contains 'req-123'

## Honesty conditions

- the announcement's six nouns (whoami, search, page, db, block, comment) are all registered in `_build_parser` and each appears in 'notion learn' output
- git diff main -- `notion_agent`/cli/`_errors.py` `notion_agent`/cli/`_output.py` `notion_agent`/explain/`__init__.py` is empty
- uv run teken cli doctor . --strict passes in a shell with `NOTION_API_KEY` unset
- every verb's --json output is a single JSON document on stdout that an agent can parse without scraping text
- git show main:pyproject.toml has dependencies = \[\] and main has no `notion_agent`/notion/ package
- the README's CLI table lists whoami, search, page, db, block, comment verbs and each example there runs as written
- the follow-up lane issue references the ids, Markdown and dry-run contracts shipped here rather than re-deciding them
- the PR description quotes the live whoami + page create/get outputs and links a green CI run
- a test runs a dry-run write and a failing request with a token value 'secret-xyz' and asserts 'secret-xyz' appears in neither stdout nor stderr

## Success signals

- live: 'uv run notion whoami' names workspace Sparkrun; 'page create --parent <Getting Started> --body md --apply' then 'page get' round-trips the Markdown; CI: pytest (fixture transport, no network), the four lint gates, markdownlint, and 'teken cli doctor --strict' all green

## Scope / boundaries

- stable-contract modules `_errors.py`, `_output.py`, explain/`__init__.py` are not modified; only catalog ENTRIES grow
- teken cli doctor --strict exercises learn/explain/overview/doctor but not whoami, so whoami may exit 2 without `NOTION_API_KEY` without breaking the rubric gate in token-less CI
- the bearer token never reaches stdout or stderr: dry-run plans print method, path and body only (no headers), and NotionError messages carry Notion's message + `request_id`, never the Authorization value

## Non-goals

- surface 2 (the communication lane: schema, lane init, send/receive, vendorable skill) is not built in this pass — it needs surface 1 first; README states the lane split and it is filed as a follow-up issue

## Assumptions

- client pins Notion-Version 2026-03-11 (current latest per developers.notion.com/reference/versioning): databases expose `data_sources`\[\]; query is POST /v1/`data_sources`/{id}/query; old /databases/{id}/query returns 400 `invalid_request_url`; archived is `in_trash`; append uses position not after; search filter values are page|`data_source`
- the client stays zero-dependency (urllib.request) — pyproject dependencies=\[\] remains true; CLAUDE.md anticipated a client dep but urllib covers the surface and keeps the mesh install weightless
- users/me returns bot.owner.type == 'user' for a personal access token (observed live) and 'workspace' for an internal integration token; whoami handles both and reports `workspace_name` from bot.`workspace_name`

## Scope exploration

- `s1` — `notion_agent/cli/__init__.py + _commands/cli.py`: `_build_parser` has a commented extension point; nested subparsers must pass `parser_class`=type(p) or lose the structured error contract
  - seeds: `c1`
- `s2` — `notion_agent/explain/catalog.py + tests/test_cli.py`: catalog coverage is enforced both ways by the parser-walk tests; root aliases (), notion, notion-agent are exempt
  - seeds: `c2`
- `s3` — `Notion API live probe (users/me, search, databases, data_sources, blocks/children, comments) + upgrade guides 2025-09-03 and 2026-03-11`: token is a personal access token for workspace Sparkrun (bot Spark); users list is `restricted_resource` for PATs; 404 `object_not_found` message already names the integration; rate limit ~3 rps with Retry-After on 429
  - seeds: `c3`
- `s4` — `pyproject.toml dependencies=[] + CLAUDE.md 'The CLI' section`: the scaffold's zero-dep posture can be preserved with urllib; departure is not required
  - seeds: `c4`
- `s5` — `cli/_errors.py, cli/_output.py, explain/__init__.py docstrings`: marked stable-contract; adding nouns needs none of them changed
  - seeds: `c5`
- `s6` — `issue #1 'Surface 2 — the communication lane'`: the lane is a convention + skill on top of the control CLI; build 1 first per the brief
  - seeds: `c6`
- `s7` — `uv run teken cli doctor . --strict output`: rubric checks: structure, learnability, json, errors, explain, overview, doctor — whoami is not invoked
  - seeds: `c7`
- `s8` — `challenge pass / adjacent-systems lens: cli/_commands/learn.py + overview.py`: `_VERBS` and the learn text are literal strings that drift silently when nouns are added; seeded a coverage requirement
  - seeds: `c23`
- `s9` — `challenge pass / unstated-assumptions lens: live GET /users/me`: the probe token is a PAT (owner.type user, name Spark, workspace Sparkrun); internal-integration shape differs only in owner
  - seeds: `c24`
- `s10` — `challenge pass / failure-modes lens: notion_agent/notion/client.py retry loop`: a blind 5xx retry on POST/PATCH can double-create pages/comments; split the retry policy by method
  - seeds: `c25`
- `s11` — `challenge pass / failure-modes lens: markdown.py BLOCKS_PER_REQUEST + page create`: multi-request creates can half-complete; the id must surface on partial failure
  - seeds: `c26`
- `s12` — `challenge pass / security lens: client.py headers() + dry-run plan rendering`: the dry-run plan is the one place a request is echoed; headers must be excluded from it
  - seeds: `c27`
- `s13` — `challenge pass / reversibility lens: upgrade guide 2026-03-11 in_trash + DELETE /blocks`: DELETE /blocks trashes; PATCH `in_trash`=false restores; add block restore for symmetry
  - seeds: `c28`
- `s14` — `challenge pass / observability lens: live 404/401 responses`: Notion returns `request_id` on every error; the stable CliError shape has no extra field, so it rides inside message
  - seeds: `c29`
- `s15` — `challenge pass / concurrency lens: PATCH /pages partial-update semantics + append`: clean pass: page update sends only the given properties and append is additive, so two agents editing one page cannot clobber each other's properties; a race on the same `rich_text` block via block update is last-writer-wins and is left as residual risk
- `s16` — `challenge pass / cheap-probe lens: POST /pages with 3-level nested children (probe page created then trashed)`: the API accepted l1>l2>l3 nesting in one request and all three levels read back — no artificial nesting limit is needed in `markdown_to_blocks`
- `s17` — `challenge pass / overlooked-actors lens: AGENTS.colleague.md`: the colleague resident prompt names no verbs today, so the new nouns do not force a prompt-file edit; the file stays as is this pass

## Decisions

- auth model: internal/personal token from the environment, `NOTION_API_KEY` first then `NOTION_TOKEN`; the token is injectable on NotionClient so a grant-backed source can be added later (issue #1 parked unknown 1 and 5)
- no workspace or parent page id is hardcoded; parents come from --parent <id-or-url> and whoami reports the workspace the token resolves to (issue #1 parked unknown 2)
- no real-time: Notion has no push, so promptness is a polling design for the lane; anything needing sub-second delivery belongs in culture (IRC) or events-cli (issue #1 parked unknown 4) — written into README's lane-split table
- db verbs address data sources (the 2025-09-03 model); a database id is accepted and resolved to its single data source, with an error listing the choices when a database has several
- destructive verbs map to Notion's trash, never a hard delete: 'page archive' / 'block delete' set `in_trash` (the API offers nothing stronger) and 'page restore' / 'block restore' undo them — recorded so agents know every write is reversible from the Notion UI or the CLI

## Open parks

- [unknown_nonblocking] grant-based secret retrieval (issue #1 parked unknown 5): env var `NOTION_API_KEY` (fallback `NOTION_TOKEN`) for now; auth is injectable via NotionClient(token=...)
- [unknown_nonblocking] a future Notion-Version bump changes wire shapes (as 2025-09-03 and 2026-03-11 did); `NOTION_VERSION` override exists but the verbs are written for 2026-03-11 only — re-verify against the upgrade guide when Notion publishes the next version
- [unknown_nonblocking] block update on the same block by two agents is last-writer-wins; the lane design (surface 2) must not rely on in-place edits for state that several agents write
