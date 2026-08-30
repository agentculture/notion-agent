"""``notion-agent search`` — find pages and data sources the integration can see.

One verb, read-only: ``POST /search`` through
:meth:`notion_agent.notion.client.NotionClient.search`. The API's filter takes
the 2025-09-03+ object values ``page`` and ``data_source`` (never
``database``), which ``--pages`` / ``--data-sources`` select.

Text output is one tab-separated row per hit (``object``, ``id``, ``title``,
``url``) so it pipes into ``cut``/``awk``; ``--json`` emits the same fields as a
list of objects and ``--json --raw`` emits Notion's raw objects untouched. Zero
results print nothing and exit ``0`` — an empty workspace is not an error.
"""

from __future__ import annotations

import argparse

from notion_agent.cli._commands._common import (
    add_json_flag,
    get_client,
    json_mode,
    notion_command,
)
from notion_agent.cli._output import emit_result
from notion_agent.notion import props

DEFAULT_LIMIT = 20


def _summarise(item: dict) -> dict:
    return {
        "object": item.get("object", ""),
        "id": item.get("id", ""),
        "title": props.page_title(item),
        "url": item.get("url", ""),
        "parent": item.get("parent"),
        "last_edited_time": item.get("last_edited_time"),
    }


def cmd_search(args: argparse.Namespace) -> None:
    kind = None
    if getattr(args, "pages", False):
        kind = "page"
    elif getattr(args, "data_sources", False):
        kind = "data_source"

    client = get_client(args)
    results = list(client.search(args.query or "", kind=kind, limit=args.limit))

    if json_mode(args):
        payload = results if getattr(args, "raw", False) else [_summarise(r) for r in results]
        emit_result(payload, json_mode=True)
        return

    if not results:
        return
    lines = []
    for item in results:
        row = _summarise(item)
        lines.append(f"{row['object']}\t{row['id']}\t{row['title']}\t{row['url']}")
    emit_result("\n".join(lines), json_mode=False)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "search",
        help="Search pages and data sources shared with the integration.",
        description="Search the workspace for pages and data sources the integration can see.",
    )
    p.add_argument("query", nargs="?", default="", help="Text to search for (omit to list all).")
    kinds = p.add_mutually_exclusive_group()
    kinds.add_argument("--pages", action="store_true", help="Only pages.")
    kinds.add_argument("--data-sources", action="store_true", help="Only data sources.")
    p.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum results (default {DEFAULT_LIMIT}).",
    )
    p.add_argument("--raw", action="store_true", help="With --json, emit raw API objects.")
    add_json_flag(p)
    p.set_defaults(func=notion_command(cmd_search))
