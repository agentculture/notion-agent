# Delivery Summary — notion control CLI

plan: `notion-control-cli` · run: `complete` · date: `2026-08-30`
baseline: `devague summary skeleton`

## Intent

Ship surface 1 of issue #1 — the Notion control CLI — as the converged plan
`notion-control-cli` (nine tasks, five waves): a zero-dependency client layer,
Markdown ⇄ blocks, typed property values, `whoami` as the auth probe, and the
`search` / `page` / `db` / `block` / `comment` nouns with dry-run-by-default
writes, wired into the catalog, documented, verified live, and merged.

## Planned Work

Quoted verbatim from the `devague summary` skeleton:

- `t1` — Markdown ⇄ blocks: `notion_agent`/notion/markdown.py pure functions + tests/`test_markdown.py` round-trip
- `t2` — Property values: `notion_agent`/notion/props.py — `flatten_properties` for reading, `build_properties`(schema, \['K=V'\]) for writing, read-only types refused; tests/`test_props.py`
- `t3` — Client layer: `notion_agent`/notion/client.py + ids.py — auth from env (`NOTION_API_KEY` then `NOTION_TOKEN`, injectable), Notion-Version 2026-03-11, 3 rps throttle, 429 retry on any method / 5xx retry only on GET with Retry-After + jitter, paginate(), `request_id` in NotionError; tests/`test_client.py` + tests/`test_ids.py` with a fake transport
- `t4` — whoami becomes the auth probe: keeps the culture.yaml identity block, adds workspace/integration/token-source/api-version from GET /users/me (PAT and internal-integration owner shapes); missing token exits 2 naming `NOTION_API_KEY`
- `t5` — search + page nouns: cli/`_commands`/`_common.py` (`get_client`, NotionError→CliError mapping incl. 'not shared with integration <name>' on 404, dry-run plan emitter that prints method/path/body only), search.py, page.py (get/create/update/append/archive/restore) — all writes dry-run unless --apply, >100-block create = create + appends with the page id in any partial-failure error; tests/`test_notion_cli.py`
- `t6` — db + block + comment nouns: db.py (get/query with --where and --filter JSON, row create/update; database id resolves to its single data source or errors listing choices), block.py (get/children/append/update/delete/restore), comment.py (list/add); tests
- `t7` — Register nouns + catalog + learn/overview: wire register() calls in `_build_parser`, add explain ENTRIES for every path, update learn text/JSON and overview `_VERBS`, add a test that every top-level registered noun is named in learn output
- `t8` — Docs + release: README (status, CLI table with all six nouns, lane-split table, trademark note), CLAUDE.md (architecture as built, decisions), docs/decisions.md for issue #1's parked unknowns, version bump 0.9.0 + CHANGELOG, file the surface-2 lane follow-up issue citing the shipped contracts
- `t9` — Live verification + PR: run whoami, search, page create --apply under 'Getting Started', page get round-trip, then trash the test page; open the PR via the cicd skill quoting those outputs; await green CI; close issue #1 with a summary

## Actual Delivery

| Plan task | Status | What actually landed |
|-----------|--------|----------------------|
| `t1` | delivered | `notion_agent/notion/markdown.py` (round-trip identity test in `tests/test_markdown.py`); later refactored to a `_RENDERERS` table + `_Parser` for SonarCloud — main agent |
| `t2` | delivered | `notion_agent/notion/props.py` + `tests/test_props.py`; `build_schema` added later for `db create` — main agent |
| `t3` | delivered | `notion_agent/notion/client.py`, `ids.py`, `tests/test_client.py`, `tests/test_ids.py`, plus `cli/_commands/_common.py` pulled into wave 0 for file-disjointness — main agent |
| `t4` | delivered | `whoami.py` + `tests/test_whoami.py` by **colleague** (`ask-colleague write`, work item `97531203a23c`, branch merged unchanged after the lint gates passed) |
| `t5` | delivered | `search.py`, `page.py`, `tests/test_page_cli.py` by an opus subagent in worktree `notion/t5` (test file named `test_page_cli.py`, not the plan's `test_notion_cli.py`) |
| `t6` | delivered | `db.py`, `block.py`, `comment.py`, `tests/test_db_block_comment_cli.py` by an opus subagent in worktree `notion/t6` |
| `t7` | delivered | nouns registered, 25 catalog entries, `learn`/`overview` updated, `test_every_top_level_noun_is_named_in_learn` — main agent |
| `t8` | delivered | README, CLAUDE.md, `docs/decisions.md`, CHANGELOG 0.9.0, follow-up issue #3 — main agent |
| `t9` | delivered | live checks against Sparkrun (page round-trip byte-identical; `Agents db` created, populated, queried, updated), PR #4 merged as `aebdeb6`, issue #1 closed — main agent |

## Mid-work Decisions

No `devague deviate` records exist for this run; the decisions below are captured directly.

- `_common.py` (planned inside `t5`) was written by the main agent in wave 0 — both `t5` and `t6` needed it, and a shared file across two same-wave worktrees would have collided at merge.
- `db create` was added (not in the plan) at the operator's request during live verification, with `props.build_schema`, catalog/README/learn entries and tests.
- SonarCloud raised 45 new-code issues after the first push; all were fixed in four commits (invariant `return 0` in handlers → `None`; help-string constants; overlap-free line regexes; dispatch-table refactors of `markdown.py`, `props.py` and `client.paginate`), ending at 0.
- Qodo found three real bugs in the wave-1 subagent code (positioned appends losing `position` after the first 100-block chunk in `page append` and `block append`; `comment add --discussion` still demanding a page id) — fixed via a shared `_common.append_in_chunks`, with tests, and replied to on the threads.
- A **1000-line ceiling on every tracked code file** (`tests/test_file_lengths.py`, covering source, tests, workflows, configs and vendored skills) was added at the operator's request.
- The colleague review of the branch (`ask-colleague review --effort xhigh`) was cut twice by the harness (1800 s stream guard / step-stall at step 6 — the local vLLM was shared with another session's benchmark and `xhigh` turns overran the output budget); a third resume with the guards lifted and `medium` effort reached step 13/20 and was **stopped at the operator's request** to merge. Its partial verdict: write verbs are gated by `--apply` and the retry policy is correct.
- `docs/specs/` and `docs/plans/` were excluded from markdownlint (devague-exported artifacts with `<placeholder>` text).
- The `.eidetic/memory` records written this session were not included in PR #4; they ship with this summary.

## Drift From Plan

| Plan item | Reason for divergence | Classification |
|-----------|-----------------------|----------------|
| `t5` | test file is `tests/test_page_cli.py`, not the plan's `tests/test_notion_cli.py`; `_common.py` landed in wave 0 instead of inside t5 | acceptable |
| `t9` | the test page was archived and then **restored** (not left trashed) so the operator could validate it; the `Agents db` and its rows remain in the workspace by request | acceptable |
| `t9` | the PR was opened as a draft before the model reviews landed, then marked ready to trigger Qodo; the colleague review never completed and was stopped — the "second mind" gate was only partially exercised | needs-follow-up |

## Evidence

- tests: `uv run pytest -q -n auto` on `main` @ `aebdeb6` — 262 passed (including `tests/test_markdown.py::test_round_trip_is_identity_on_canonical_markdown`, `tests/test_page_cli.py::test_page_append_after_threads_position_through_every_chunk`, `tests/test_whoami.py`, `tests/test_file_lengths.py`)
- lint: `uv run flake8 notion_agent tests` — clean; CI `lint` job (black, isort, flake8, bandit, markdownlint, `teken cli doctor --strict`) — pass
- SonarCloud on PR #4 — quality gate passed, 0 new issues at merge, 91.9% coverage on new code
- commits: `687c74b..aebdeb6` (squash of the 18-commit branch `notion/control-cli`)
- PRs / issues: #4 (merged), #1 (closed), #3 (follow-up: the lane)
- live: <https://app.notion.com/p/notion-agent-live-check-3cc523dc87bf81d2a514ed9e5ed24c0e>, <https://app.notion.com/p/990eea9b4e9f4c289969dc52dedfabb3> (Agents db)
- colleague work items: `97531203a23c` (t4, graded 4/5), `5ffc0595d92c` / `bbc9d432be91` (review, graded 2/5 — cut)

## Delivery Claims

| Claim | Confidence | Evidence |
|-------|------------|----------|
| every write verb is dry-run by default and `--apply` performs it | high | `tests/test_page_cli.py`, `tests/test_db_block_comment_cli.py` (`fake.mutations() == []` without `--apply`) · live dry-run outputs quoted in PR #4 |
| `whoami` probes the token and exits 2 without one | high | `tests/test_whoami.py` · live output in PR #4 |
| a page created from Markdown reads back as the same Markdown | high | `test_round_trip_is_identity_on_canonical_markdown` · live `diff` = identical (PR #4) |
| 404s surface as "not shared with the integration NAME" with `request_id` | high | `tests/test_page_cli.py` 404 tests · live bogus-id output in PR #4 |
| `5xx` is never retried for writes; `429` is retried with Retry-After | high | `tests/test_client.py::test_5xx_retried_only_for_get`, `::test_429_retried_with_retry_after_on_post` |
| the token never reaches stdout/stderr | high | `tests/test_client.py::test_error_carries_notion_fields` + CLI token-leak tests |
| `db create\|get\|query\|row create\|row update` work against the 2026-03-11 data-source model | high | `tests/test_db_block_comment_cli.py` · live `Agents db` (PR #4) |
| the runtime has no third-party dependencies | high | `pyproject.toml` `dependencies = []` · `tests/test_client.py` |
| no code file exceeds 1000 lines | high | `tests/test_file_lengths.py` (63 files checked) |
| the branch received an independent second-mind review | low | colleague review partial only (`5ffc0595d92c`); Qodo and `/code-review` findings addressed — the colleague verdict beyond "writes gated, retries correct" is **unverified** |

## Remaining Work / Follow-up

- Surface 2 — the communication lane (schema, `lane init`, send/receive, vendorable skill) — issue #3.
- A completed colleague review of `notion_agent/notion/markdown.py`, `props.py` and `whoami.py` (the areas its cut runs never reached) — re-run `ask-colleague review` once the shared vLLM is idle, with a narrower brief and default effort.
- Ask guildmaster whether the 1000-line ceiling should be broadcast as a mesh-wide convention (it currently lives only in this repo's test suite).
