# Decisions — the Notion control CLI

Issue [#1](https://github.com/agentculture/notion-agent/issues/1) parked five
unknowns and asked for each decision to be recorded with its reasoning. These
were settled through the devague method (`/scope` → `/think` → `/challenge` →
`/spec-to-plan`); the converged frame is exported at
[`docs/specs/2026-08-30-notion-control-cli.md`](specs/2026-08-30-notion-control-cli.md)
and the build plan at
[`docs/plans/2026-08-30-notion-control-cli.md`](plans/2026-08-30-notion-control-cli.md).
Claim ids below (`cN`) refer to the spec.

## 1. Auth model — token from the environment, injectable (c19)

An internal-integration or personal access token read from `NOTION_API_KEY`
(fallback `NOTION_TOKEN`). Public OAuth is a much larger surface with no
mesh consumer asking for it. The token is a constructor argument on
`NotionClient`, so a `grant`-backed source can be wired in later without
touching any verb (see 5).

## 2. Which workspace / parent page — never hardcoded (c20)

No workspace or page id lives in code or config. Parents come from
`--parent <id-or-url>` on the verb; `notion whoami` reports which workspace
and integration the token resolves to, so an agent can check before writing.

## 3. Access scope — the "not shared" error is first-class (c16)

A Notion integration only sees pages explicitly shared with it, and the API
answers `404 object_not_found` for anything else. The CLI maps that to
`object not found or not shared with the integration '<name>'` with a
remediation naming the Connections menu — never a bare 404. The integration
name is parsed from Notion's own message, and Notion's `request_id` rides
along in every error (c29).

## 4. Real-time — no; the lane will poll (c21)

Notion has no push. A consumer that needs promptness polls with a cursor or a
status filter; anything needing sub-second delivery belongs in `culture`
(IRC) or `events-cli` (MQTT). The README's lane-split table says so.

## 5. Secrets handling — `grant` deferred (frame v1)

The mesh's `grant` is not used yet: the environment variable is the pragmatic
default for a single-workspace mesh and keeps the runtime dependency-free.
Because auth is injectable (1), adopting `grant` is a client-factory change,
not a verb change.

## Other decisions the frame settled

- **API version `2026-03-11`, pinned in the client (c4).** Databases expose
  `data_sources[]`; queries are `POST /v1/data_sources/{id}/query` (the old
  `/databases/{id}/query` returns `400 invalid_request_url`); trash is
  `in_trash`; block positioning is `position`. `NOTION_VERSION` overrides the
  header, but the verbs are written for this version only (plan risk r2).
- **Zero runtime dependencies (c5).** The client is `urllib` — `dependencies =
  []` stays true and a mesh install stays weightless. `CLAUDE.md` once expected
  a client dependency; `urllib` covers the surface, so none was taken.
- **Every write is dry-run by default; `--apply` commits (c14).** No
  exceptions — agents call this in loops and Notion writes are hard to reverse.
- **Destructive verbs map to Notion's trash (c28).** `page archive` / `block
  delete` set `in_trash` (the API offers nothing stronger); `page restore` /
  `block restore` undo them.
- **Retries never duplicate writes (c25).** `429` is retried for every method
  (the server did not process it); `5xx` is retried only for `GET`. A write
  that got a `5xx` is reported with its `request_id` instead of replayed.
- **`db` verbs address data sources (c22).** A database id is accepted and
  resolved to its single data source; a database with several fails listing
  them.
- **Markdown is the canonical text representation (c17).** `notion_agent/
  notion/markdown.py` converts both ways as pure functions with a round-trip
  test; verbs never build block JSON by hand.
- **Surface 2 — the communication lane — is deferred (c7).** It needs these
  contracts settled first; it is tracked as a follow-up issue.
