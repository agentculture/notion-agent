"""``notion-agent learn`` — the learnability affordance.

Prints a structured self-teaching prompt. Must satisfy the agent-first rubric:
>=200 chars and mention purpose, command map, exit codes, --json, and explain.
"""

from __future__ import annotations

import argparse

from notion_agent import __version__
from notion_agent.cli._output import emit_result

_TEXT = """\
notion-agent — agent-first CLI for controlling Notion.

Purpose
-------
Drive a Notion workspace from a shell: search, read pages as Markdown, create
and update pages and database rows, append and edit blocks, list and add
comments. Built for AgentCulture mesh agents; durable, human-visible output is
the point (Notion is the lane for documents and tables, not live chat).

Auth
----
Set NOTION_API_KEY (or NOTION_TOKEN) to an internal-integration or personal
access token. Pages and databases must be shared with the integration
(Notion → ... → Connections) or the API cannot see them.

Commands
--------
  notion-agent whoami                    Identity + auth probe (workspace, integration).
  notion-agent search [query]            Find pages and data sources.
  notion-agent page get|create|update|append|archive|restore
  notion-agent db get|query|row create|row update
  notion-agent block get|children|append|update|delete|restore
  notion-agent comment list|add
  notion-agent learn                     This self-teaching prompt.
  notion-agent explain <path>...         Markdown docs for any noun/verb path.
  notion-agent overview                  Descriptive snapshot of the agent.
  notion-agent doctor                    Check the agent-identity invariants.
  notion-agent cli overview              Describe the CLI surface itself.

Write safety
------------
Every write verb is a DRY RUN by default: it prints the request(s) it would
send and exits 0. Add --apply to perform it. Ids accept dashed/32-hex ids or
notion.so / app.notion.com URLs. Page bodies are Markdown.

Machine-readable output
-----------------------
Every command supports --json. Errors in JSON mode emit
{"code", "message", "remediation"} to stderr. Stdout and stderr never mix.

Exit-code policy
----------------
  0 success
  1 user-input error (bad flag, bad id, unknown property, not shared)
  2 environment / setup error (no token, token rejected, network, rate limit)
  3+ reserved

More detail
-----------
  notion-agent explain notion-agent
  notion-agent explain page create
"""


def _as_json_payload() -> dict[str, object]:
    return {
        "tool": "notion-agent",
        "version": __version__,
        "purpose": "Agent-first CLI for controlling Notion (pages, databases, blocks, "
        "comments, search); writes are dry-run unless --apply.",
        "auth": "NOTION_API_KEY (fallback NOTION_TOKEN); share pages with the integration.",
        "commands": [
            {"path": ["whoami"], "summary": "Identity + Notion auth probe."},
            {"path": ["search"], "summary": "Find pages and data sources."},
            {"path": ["page"], "summary": "get|create|update|append|archive|restore a page."},
            {"path": ["db"], "summary": "get|query a data source; row create|update."},
            {"path": ["block"], "summary": "get|children|append|update|delete|restore blocks."},
            {"path": ["comment"], "summary": "list|add comments on a page."},
            {"path": ["learn"], "summary": "Self-teaching prompt."},
            {"path": ["explain"], "summary": "Markdown docs by path."},
            {"path": ["overview"], "summary": "Descriptive snapshot of the agent."},
            {"path": ["doctor"], "summary": "Check the agent-identity invariants."},
            {"path": ["cli", "overview"], "summary": "Describe the CLI surface."},
        ],
        "exit_codes": {
            "0": "success",
            "1": "user-input error",
            "2": "environment/setup error",
        },
        "json_support": True,
        "dry_run_default": True,
        "explain_pointer": "notion-agent explain <path>",
    }


def cmd_learn(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        emit_result(_as_json_payload(), json_mode=True)
    else:
        emit_result(_TEXT, json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "learn",
        help="Print a structured self-teaching prompt for agent consumers.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_learn)
