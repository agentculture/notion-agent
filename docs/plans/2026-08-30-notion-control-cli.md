# Build Plan — notion control CLI

slug: `notion-control-cli` · status: `exported` · from frame: `notion-control-cli`

> notion-agent controls a Notion workspace from an agent-first CLI: search, page, db, block, comment nouns, dry-run-by-default writes, Markdown<->blocks, zero-dep urllib client with pagination + rate limiting, whoami as the auth probe

## Tasks

### t1 — Markdown ⇄ blocks: `notion_agent`/notion/markdown.py pure functions + tests/`test_markdown.py` round-trip

- covers: c17, h6
- acceptance:
  - `blocks_to_markdown`(`markdown_to_blocks`(sample)) == sample for headings, paragraphs, nested lists, to-dos, quote, code, divider, inline bold/italic/strike/code/link
  - rich text over 2000 chars is chunked; read-only block types render a labelled placeholder rather than vanishing

### t2 — Property values: `notion_agent`/notion/props.py — `flatten_properties` for reading, `build_properties`(schema, \['K=V'\]) for writing, read-only types refused; tests/`test_props.py`

- acceptance:
  - each supported type builds the documented payload; formula/rollup/`created_`\* raise ValueError naming the property
  - `page_title` finds the title property of a page and the title of a data source

### t3 — Client layer: `notion_agent`/notion/client.py + ids.py — auth from env (`NOTION_API_KEY` then `NOTION_TOKEN`, injectable), Notion-Version 2026-03-11, 3 rps throttle, 429 retry on any method / 5xx retry only on GET with Retry-After + jitter, paginate(), `request_id` in NotionError; tests/`test_client.py` + tests/`test_ids.py` with a fake transport

- covers: c18, c25, c29, h7, h17, h19, h11, c10
- acceptance:
  - fake transport: `has_more` pages all yielded; 429+Retry-After sleeps >= that; POST 503 raises without retry; GET 503 then 200 succeeds
  - `normalize_id` accepts dashed, 32-hex and notion.so/app.notion.com URLs (p= wins over v=)
  - pyproject dependencies stays \[\]

### t4 — whoami becomes the auth probe: keeps the culture.yaml identity block, adds workspace/integration/token-source/api-version from GET /users/me (PAT and internal-integration owner shapes); missing token exits 2 naming `NOTION_API_KEY`

- depends on: t3
- covers: c15, h4
- acceptance:
  - main(\['whoami'\]) with no token → exit 2, stderr mentions `NOTION_API_KEY`
  - fake users/me → stdout names workspace and integration; --json is one JSON document

### t5 — search + page nouns: cli/`_commands`/`_common.py` (`get_client`, NotionError→CliError mapping incl. 'not shared with integration <name>' on 404, dry-run plan emitter that prints method/path/body only), search.py, page.py (get/create/update/append/archive/restore) — all writes dry-run unless --apply, >100-block create = create + appends with the page id in any partial-failure error; tests/`test_notion_cli.py`

- depends on: t1, t2, t3
- covers: c2, c14, c16, c26, c27, h1, h3, h5, h18, h20
- acceptance:
  - each write verb without --apply sends zero mutating requests and exits 0; with --apply sends exactly the expected ones
  - fake 404 `object_not_found` → exit 1, hint contains 'shared' and the integration name and the `request_id`
  - token value never appears in stdout/stderr of a dry-run or a failing call
  - page create with 150 blocks: 1 POST /pages + 1 PATCH children; failing PATCH error names the page id

### t6 — db + block + comment nouns: db.py (get/query with --where and --filter JSON, row create/update; database id resolves to its single data source or errors listing choices), block.py (get/children/append/update/delete/restore), comment.py (list/add); tests

- depends on: t1, t2, t3
- covers: c2, c14, h1, h3
- acceptance:
  - db get <database-id> with one data source resolves; with two → exit 1 listing both ids
  - block delete / page archive are dry-run by default and map to trash; block restore / page restore undo them
  - parse errors under every nested subparser exit 1 with error:/hint:

### t7 — Register nouns + catalog + learn/overview: wire register() calls in `_build_parser`, add explain ENTRIES for every path, update learn text/JSON and overview `_VERBS`, add a test that every top-level registered noun is named in learn output

- depends on: t5, t6
- covers: c3, c23, h2, h15, h16, c6, h8, c8, h9, c1, c9, h10
- acceptance:
  - `test_every_registered_path_has_catalog_entry` and `test_no_orphan_catalog_entries` pass
  - new test: every top-level noun in the parser appears in main(\['learn'\]) stdout
  - uv run teken cli doctor . --strict passes with `NOTION_API_KEY` unset
  - git diff main on `_errors.py`/`_output.py`/explain/`__init__.py` is empty

### t8 — Docs + release: README (status, CLI table with all six nouns, lane-split table, trademark note), CLAUDE.md (architecture as built, decisions), docs/decisions.md for issue #1's parked unknowns, version bump 0.9.0 + CHANGELOG, file the surface-2 lane follow-up issue citing the shipped contracts

- depends on: t7
- covers: c12, h12, h13, c11
- acceptance:
  - README CLI table lists whoami, search, page, db, block, comment and each example runs as written
  - markdownlint-cli2 passes
  - follow-up lane issue exists and references the id/Markdown/dry-run contracts by name

### t9 — Live verification + PR: run whoami, search, page create --apply under 'Getting Started', page get round-trip, then trash the test page; open the PR via the cicd skill quoting those outputs; await green CI; close issue #1 with a summary

- depends on: t8
- covers: c13, h14
- acceptance:
  - whoami names workspace Sparkrun live
  - page create --apply then page get returns the Markdown body that was sent
  - PR body quotes live outputs and CI is green

## Risks

- [follow_up] block update by two agents on one block is last-writer-wins (frame v3) — the lane design must not depend on in-place edits for multi-writer state
- [unknown_nonblocking] the next Notion-Version bump changes wire shapes (frame v2); `NOTION_VERSION` override exists but verbs target 2026-03-11 only
