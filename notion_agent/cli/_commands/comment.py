"""``notion-agent comment`` — read and add comments on pages and blocks.

Comments are the low-friction lane between agents: ``comment list`` reads a
discussion, ``comment add`` posts into one (``--discussion``) or starts a new
thread on a page. Adding is a dry run unless ``--apply``.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from notion_agent.cli._commands._common import (
    Plan,
    add_apply_flag,
    add_body_flags,
    add_json_flag,
    applying,
    emit_plan,
    get_client,
    json_mode,
    notion_command,
    noun_help,
    parse_id,
    read_body,
)
from notion_agent.cli._errors import EXIT_USER_ERROR, CliError
from notion_agent.cli._output import emit_result
from notion_agent.notion.markdown import markdown_to_rich_text, plain_text


def _author(comment: dict[str, Any]) -> str:
    created_by = comment.get("created_by") or {}
    return str(created_by.get("name") or created_by.get("id") or "")


@notion_command
def cmd_list(args: argparse.Namespace) -> None:
    client = get_client(args)
    target = parse_id(args.id, "page or block id")
    comments = list(client.list_comments(target, limit=args.limit))
    as_json = json_mode(args)
    if args.raw:
        emit_result(comments if as_json else json.dumps(comments, indent=2), json_mode=as_json)
        return
    rows = [
        {
            "id": c.get("id"),
            "discussion_id": c.get("discussion_id"),
            "created_time": c.get("created_time"),
            "author": _author(c),
            "text": plain_text(c.get("rich_text")),
        }
        for c in comments
    ]
    if as_json:
        emit_result(rows, json_mode=True)
        return
    if not rows:
        return
    emit_result(
        "\n".join(
            "\t".join([str(r["created_time"] or ""), str(r["author"]), str(r["text"])])
            for r in rows
        ),
        json_mode=False,
    )


@notion_command
def cmd_add(args: argparse.Namespace) -> None:
    client = get_client(args)
    text = read_body(args)
    if not text or not text.strip():
        raise CliError(
            code=EXIT_USER_ERROR,
            message="the comment body is empty",
            remediation="pass --body '<text>' or --body-file <path>",
        )
    body: dict[str, Any] = {"rich_text": markdown_to_rich_text(text.strip())}
    if args.discussion:
        body = {"discussion_id": args.discussion, **body}
        summary = f"add a comment to discussion {args.discussion}"
    else:
        page_id = parse_id(args.id, "page id")
        body = {"parent": {"page_id": page_id}, **body}
        summary = f"add a comment to page {page_id}"
    plan = Plan(summary)
    plan.add("POST", "/comments", body)
    if not applying(args):
        emit_plan(plan, json_mode=json_mode(args))
        return
    created = client.request("POST", "/comments", body=body)
    comment_id = created.get("id", "")
    if json_mode(args):
        emit_result(
            {"id": comment_id, "discussion_id": created.get("discussion_id")}, json_mode=True
        )
    else:
        emit_result(f"added comment {comment_id}", json_mode=False)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("comment", help="Comments on pages and blocks.")
    add_json_flag(p)
    p.set_defaults(func=noun_help(p), json=False)
    noun = p.add_subparsers(dest="comment_command", parser_class=type(p))

    listing = noun.add_parser("list", help="List comments on a page or block.")
    listing.add_argument("id", help="Page or block id, or Notion URL.")
    listing.add_argument("--limit", type=int, default=None, help="Max comments to return.")
    add_json_flag(listing)
    listing.add_argument("--raw", action="store_true", help="Emit the raw Notion API payload.")
    listing.set_defaults(func=cmd_list)

    add = noun.add_parser("add", help="Add a comment to a page or discussion.")
    add.add_argument("id", help="Page id or Notion URL (ignored with --discussion).")
    add_body_flags(add, required=True)
    add.add_argument("--discussion", help="Reply into an existing discussion id.")
    add_apply_flag(add)
    add_json_flag(add)
    add.set_defaults(func=cmd_add)
