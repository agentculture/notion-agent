"""``notion-agent block`` — the block tree: read, append, edit, trash, restore.

Content is always exchanged as Markdown (:mod:`notion_agent.notion.markdown`);
no verb here builds block JSON by hand. Every write is a dry run unless
``--apply``.

Trash semantics (Notion 2026-03-11): ``DELETE /blocks/{id}`` *trashes* a block
rather than destroying it, and ``PATCH /blocks/{id}`` with ``{"in_trash":
false}`` puts it back — hence the ``delete`` / ``restore`` pair. Appends use the
``position`` field (``after_block``); the pre-2026 ``after`` field is never sent.
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
    run_plan,
)
from notion_agent.cli._errors import EXIT_USER_ERROR, CliError
from notion_agent.cli._output import emit_result
from notion_agent.notion.markdown import (
    BLOCKS_PER_REQUEST,
    blocks_to_markdown,
    chunk_blocks,
    markdown_to_blocks,
    markdown_to_rich_text,
)

DEFAULT_DEPTH = 3


def _add_raw_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument("--raw", action="store_true", help="Emit the raw Notion API payload.")


def _emit_raw(payload: Any, *, json_mode_on: bool) -> None:
    emit_result(payload if json_mode_on else json.dumps(payload, indent=2), json_mode=json_mode_on)


def _parent_label(block: dict[str, Any]) -> str:
    parent = block.get("parent") or {}
    ptype = parent.get("type", "")
    return f"{ptype} {parent.get(ptype, '')}".strip()


def _count(blocks: list[dict[str, Any]]) -> int:
    return sum(1 + _count(b.get("children") or []) for b in blocks)


# --------------------------------------------------------------------------
# read verbs
# --------------------------------------------------------------------------

_ID_HELP = "Block id or Notion URL."
_ID_WHAT = "block id"


@notion_command
def cmd_get(args: argparse.Namespace) -> None:
    client = get_client(args)
    block_id = parse_id(args.id, _ID_WHAT)
    block = client.get_block(block_id)
    as_json = json_mode(args)
    if args.raw:
        _emit_raw(block, json_mode_on=as_json)
        return
    markdown = blocks_to_markdown([block])
    if as_json:
        emit_result(
            {
                "id": block.get("id"),
                "type": block.get("type"),
                "parent": block.get("parent"),
                "has_children": bool(block.get("has_children")),
                "in_trash": bool(block.get("in_trash")),
                "markdown": markdown,
            },
            json_mode=True,
        )
        return
    lines = [
        f"type: {block.get('type', '')}",
        f"id: {block.get('id', '')}",
        f"parent: {_parent_label(block)}",
        f"has_children: {str(bool(block.get('has_children'))).lower()}",
        "",
        markdown,
    ]
    emit_result("\n".join(lines), json_mode=False)


@notion_command
def cmd_children(args: argparse.Namespace) -> None:
    client = get_client(args)
    block_id = parse_id(args.id, _ID_WHAT)
    blocks = client.block_tree(block_id, depth=args.depth)
    markdown = blocks_to_markdown(blocks)
    as_json = json_mode(args)
    if args.raw and not as_json:
        _emit_raw(blocks, json_mode_on=False)
        return
    if as_json:
        payload: dict[str, Any] = {
            "id": block_id,
            "markdown": markdown,
            "count": _count(blocks),
        }
        if args.raw:
            payload["raw"] = blocks
        emit_result(payload, json_mode=True)
        return
    emit_result(markdown, json_mode=False)


# --------------------------------------------------------------------------
# write verbs
# --------------------------------------------------------------------------


@notion_command
def cmd_append(args: argparse.Namespace) -> None:
    client = get_client(args)
    block_id = parse_id(args.id, _ID_WHAT)
    markdown = read_body(args)
    if not markdown or not markdown.strip():
        raise CliError(
            code=EXIT_USER_ERROR,
            message="the body is empty; nothing to append",
            remediation="pass --body '<markdown>' or --body-file <path>",
        )
    blocks = markdown_to_blocks(markdown)
    chunks = chunk_blocks(blocks, BLOCKS_PER_REQUEST)
    after = parse_id(args.after, _ID_WHAT) if args.after else None

    plan = Plan(f"append {len(blocks)} block(s) to {block_id}")
    for index, chunk in enumerate(chunks):
        body: dict[str, Any] = {"children": chunk}
        if after and index == 0:
            body["position"] = {"type": "after_block", "after_block": {"id": after}}
        plan.add(
            "PATCH",
            f"/blocks/{block_id}/children",
            body,
            describe=f"chunk {index + 1} of {len(chunks)}",
        )
    if not applying(args):
        emit_plan(plan, json_mode=json_mode(args))
        return
    run_plan(client, plan)
    _emit_done(args, f"appended {len(blocks)} block(s) to {block_id}", block_id)


@notion_command
def cmd_update(args: argparse.Namespace) -> None:
    client = get_client(args)
    block_id = parse_id(args.id, _ID_WHAT)
    block = client.get_block(block_id)
    btype = block.get("type", "")
    payload = block.get(btype) or {}
    if not isinstance(payload, dict) or "rich_text" not in payload:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"block {block_id} is a '{btype}' block, which has no editable text",
            remediation="delete it and append a replacement, or edit a text block instead",
        )
    body = {btype: {"rich_text": markdown_to_rich_text(args.text)}}
    plan = Plan(f"replace the text of {btype} block {block_id}")
    plan.add("PATCH", f"/blocks/{block_id}", body)
    if not applying(args):
        emit_plan(plan, json_mode=json_mode(args))
        return
    run_plan(client, plan)
    _emit_done(args, f"updated block {block_id}", block_id)


@notion_command
def cmd_delete(args: argparse.Namespace) -> None:
    client = get_client(args)
    block_id = parse_id(args.id, _ID_WHAT)
    plan = Plan(f"move block {block_id} to the trash")
    plan.add("DELETE", f"/blocks/{block_id}", describe="Notion trashes the block; it is reversible")
    if not applying(args):
        emit_plan(plan, json_mode=json_mode(args))
        return
    run_plan(client, plan)
    _emit_done(args, f"deleted block {block_id} (in trash)", block_id)


@notion_command
def cmd_restore(args: argparse.Namespace) -> None:
    client = get_client(args)
    block_id = parse_id(args.id, _ID_WHAT)
    plan = Plan(f"restore block {block_id} from the trash")
    plan.add("PATCH", f"/blocks/{block_id}", {"in_trash": False})
    if not applying(args):
        emit_plan(plan, json_mode=json_mode(args))
        return
    run_plan(client, plan)
    _emit_done(args, f"restored block {block_id}", block_id)


def _emit_done(args: argparse.Namespace, message: str, block_id: str) -> None:
    if json_mode(args):
        emit_result({"id": block_id, "result": message}, json_mode=True)
    else:
        emit_result(message, json_mode=False)


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("block", help="Blocks: read, append, edit, trash, restore.")
    add_json_flag(p)
    p.set_defaults(func=noun_help(p), json=False)
    noun = p.add_subparsers(dest="block_command", parser_class=type(p))

    get = noun.add_parser("get", help="Show one block.")
    get.add_argument("id", help=_ID_HELP)
    add_json_flag(get)
    _add_raw_flag(get)
    get.set_defaults(func=cmd_get)

    children = noun.add_parser("children", help="Render a block's children as Markdown.")
    children.add_argument("id", help="Block or page id, or Notion URL.")
    children.add_argument(
        "--depth", type=int, default=DEFAULT_DEPTH, help=f"Nesting depth (default {DEFAULT_DEPTH})."
    )
    add_json_flag(children)
    _add_raw_flag(children)
    children.set_defaults(func=cmd_children)

    append = noun.add_parser("append", help="Append Markdown as child blocks.")
    append.add_argument("id", help="Block or page id, or Notion URL.")
    add_body_flags(append, required=True)
    append.add_argument("--after", help="Insert after this existing child block id.")
    add_apply_flag(append)
    add_json_flag(append)
    append.set_defaults(func=cmd_append)

    update = noun.add_parser("update", help="Replace a text block's content.")
    update.add_argument("id", help=_ID_HELP)
    update.add_argument("--text", required=True, help="Replacement Markdown (one line).")
    add_apply_flag(update)
    add_json_flag(update)
    update.set_defaults(func=cmd_update)

    delete = noun.add_parser("delete", help="Move a block to the trash.")
    delete.add_argument("id", help=_ID_HELP)
    add_apply_flag(delete)
    add_json_flag(delete)
    delete.set_defaults(func=cmd_delete)

    restore = noun.add_parser("restore", help="Restore a block from the trash.")
    restore.add_argument("id", help=_ID_HELP)
    add_apply_flag(restore)
    add_json_flag(restore)
    restore.set_defaults(func=cmd_restore)
