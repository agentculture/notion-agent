"""``notion-agent page`` — read and write Notion pages.

Verbs: ``get`` (read a page as Markdown), ``create``, ``update``, ``append``,
``archive`` and ``restore``. Every id argument accepts a raw id, a 32-hex id, or
a Notion URL (:func:`notion_agent.notion.ids.normalize_id` via ``parse_id``).

Contracts this module upholds (all shared, none re-derived here):

* **dry run by default** — every write builds a :class:`Plan` and prints it
  (exit ``0``, zero mutating requests) unless ``--apply`` is passed.
* **Markdown is the text representation** — bodies go through
  :func:`markdown_to_blocks` / :func:`blocks_to_markdown`; no verb hand-builds
  block JSON.
* **partial creates name the page** — a body over 100 blocks is one
  ``POST /pages`` plus follow-up ``PATCH /blocks/{id}/children`` requests. If a
  follow-up fails, the error carries the *created* page id and a ready-to-run
  ``page append`` command, so an agent resumes instead of re-creating.
* **2026-03-11 shapes** — trashing is ``in_trash`` (never ``archived``) and
  positioned appends use ``position.after_block`` (never the old ``after``).
"""

from __future__ import annotations

import argparse
from typing import Any

from notion_agent.cli._commands._common import (
    Plan,
    add_apply_flag,
    add_body_flags,
    add_json_flag,
    append_in_chunks,
    append_plan,
    applying,
    emit_plan,
    get_client,
    json_mode,
    notion_command,
    noun_help,
    parse_id,
    read_body,
    resolve_data_source,
    run_plan,
    to_cli_error,
)
from notion_agent.cli._errors import EXIT_USER_ERROR, CliError
from notion_agent.cli._output import emit_result
from notion_agent.notion import props
from notion_agent.notion.client import NotionClient, NotionError
from notion_agent.notion.markdown import blocks_to_markdown, chunk_blocks, markdown_to_blocks

# A dry run cannot know the id of a page it has not created yet, so the
# follow-up append steps render with this placeholder in their path.
NEW_PAGE_PLACEHOLDER = "<new-page-id>"
FOLLOW_UP_DESCRIBE = "follow-up append (page id known after create)"


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------


_ID_HELP = "Page id or Notion URL."
_ID_WHAT = "page id"


def _parent_label(parent: dict[str, Any] | None) -> str:
    if not parent:
        return ""
    ptype = parent.get("type", "")
    value = parent.get(ptype)
    return f"{ptype} {value}" if isinstance(value, str) else ptype


def _icon(emoji: str | None) -> dict[str, Any] | None:
    return {"type": "emoji", "emoji": emoji} if emoji else None


def _body_blocks(args: argparse.Namespace) -> list[dict[str, Any]]:
    body = read_body(args)
    return markdown_to_blocks(body) if body else []


def _chunks(blocks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return chunk_blocks(blocks) if blocks else []


def _title_payload(name: str, title: str) -> dict[str, Any]:
    return {name: props.build_value("title", title)}


# --------------------------------------------------------------------------
# page get
# --------------------------------------------------------------------------


def cmd_page_get(args: argparse.Namespace) -> None:
    page_id = parse_id(args.id, _ID_WHAT)
    client = get_client(args)
    page = client.get_page(page_id)
    blocks: list[dict[str, Any]] = []
    if not args.no_content:
        blocks = client.block_tree(page_id, depth=max(1, args.depth))
    markdown = blocks_to_markdown(blocks)
    flat = props.flatten_properties(page.get("properties") or {})
    record: dict[str, Any] = {
        "id": page.get("id", page_id),
        "title": props.page_title(page),
        "url": page.get("url", ""),
        "parent": page.get("parent"),
        "in_trash": bool(page.get("in_trash", False)),
        "properties": flat,
        "markdown": markdown,
    }
    if json_mode(args):
        if args.raw:
            record["raw"] = {"page": page, "blocks": blocks}
        emit_result(record, json_mode=True)
        return

    lines = [
        f"# {record['title']}",
        f"id: {record['id']}",
        f"url: {record['url']}",
        f"parent: {_parent_label(record['parent'])}",
        f"in_trash: {str(record['in_trash']).lower()}",
        "properties:",
    ]
    for name, value in flat.items():
        lines.append(f"  {name}: {_render_value(value)}")
    lines.append("")
    lines.append(markdown)
    emit_result("\n".join(lines).rstrip("\n"), json_mode=False)


def _render_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


# --------------------------------------------------------------------------
# page create
# --------------------------------------------------------------------------


def _resolve_parent(client: NotionClient, raw: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return ``(parent payload, data source or None)`` for ``--parent``.

    A page id wins if the id resolves as a page; ``object_not_found`` means it
    is not a page, so the id is retried as a data source / database id.
    """
    parent_id = parse_id(raw, "parent id")
    try:
        client.get_page(parent_id)
        return {"page_id": parent_id}, None
    except NotionError as err:
        if err.code != "object_not_found":
            raise
    data_source = resolve_data_source(client, parent_id)
    return {"data_source_id": data_source["id"]}, data_source


def _create_properties(
    args: argparse.Namespace, data_source: dict[str, Any] | None
) -> dict[str, Any]:
    sets = list(getattr(args, "set", None) or [])
    if data_source is None:
        if sets:
            raise CliError(
                code=EXIT_USER_ERROR,
                message="properties other than title need a data source parent",
                remediation=(
                    "pass --parent <data source or database id> to set properties, or drop --set"
                ),
            )
        return _title_payload("title", args.title)
    schema = data_source.get("properties") or {}
    payload = props.build_properties(schema, sets) if sets else {}
    payload.update(_title_payload(props.title_property_name(schema) or "title", args.title))
    return payload


def _create_plan(
    args: argparse.Namespace, parent: dict[str, Any], properties: dict[str, Any]
) -> tuple[Plan, list[list[dict[str, Any]]]]:
    chunks = _chunks(_body_blocks(args))
    body: dict[str, Any] = {"parent": parent, "properties": properties}
    icon = _icon(args.icon)
    if icon:
        body["icon"] = icon
    if chunks:
        body["children"] = chunks[0]
    kind, target = next(iter(parent.items()))
    plan = Plan(summary=f"create page '{args.title}' under {kind} {target}")
    plan.add("POST", "/pages", body)
    for chunk in chunks[1:]:
        plan.add(
            "PATCH",
            f"/blocks/{NEW_PAGE_PLACEHOLDER}/children",
            {"children": chunk},
            describe=FOLLOW_UP_DESCRIBE,
        )
    return plan, chunks


def cmd_page_create(args: argparse.Namespace) -> None:
    client = get_client(args)
    parent, data_source = _resolve_parent(client, args.parent)
    properties = _create_properties(args, data_source)
    plan, chunks = _create_plan(args, parent, properties)

    if not applying(args):
        emit_plan(plan, json_mode=json_mode(args))
        return

    created = client.request("POST", "/pages", body=plan.steps[0].body)
    page_id = created.get("id", "")
    appended = len(chunks[0]) if chunks else 0
    for step in plan.steps[1:]:
        try:
            client.request("PATCH", f"/blocks/{page_id}/children", body=step.body)
        except NotionError as err:
            mapped = to_cli_error(err)
            raise CliError(
                code=mapped.code,
                message=(
                    f"page {page_id} was created but appending blocks failed: {mapped.message}"
                ),
                remediation=(
                    f"resume with: notion-agent page append {page_id} "
                    "--body-file <remaining markdown> --apply"
                ),
            ) from err
        appended += len(step.body["children"])

    if json_mode(args):
        emit_result(
            {
                "id": page_id,
                "url": created.get("url", ""),
                "title": props.page_title(created) or args.title,
                "appended_blocks": appended,
            },
            json_mode=True,
        )
    else:
        emit_result(f"created page {page_id}\n{created.get('url', '')}", json_mode=False)


# --------------------------------------------------------------------------
# page update
# --------------------------------------------------------------------------


def _update_properties(
    client: NotionClient, page: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    sets = list(getattr(args, "set", None) or [])
    page_props = page.get("properties") or {}
    payload: dict[str, Any] = {}
    if sets:
        data_source_id = (page.get("parent") or {}).get("data_source_id")
        if not data_source_id:
            raise CliError(
                code=EXIT_USER_ERROR,
                message="properties other than title need a data source parent",
                remediation="this page's parent is not a data source; use --title, or drop --set",
            )
        schema = (client.get_data_source(data_source_id).get("properties")) or {}
        payload.update(props.build_properties(schema, sets))
    if args.title is not None:
        name = props.title_property_name(page_props) or "title"
        payload.update(_title_payload(name, args.title))
    return payload


def cmd_page_update(args: argparse.Namespace) -> None:
    page_id = parse_id(args.id, _ID_WHAT)
    sets = list(getattr(args, "set", None) or [])
    if args.title is None and not sets and not args.icon:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="nothing to update",
            remediation="pass at least one of --title, --set Name=value, --icon",
        )
    client = get_client(args)
    page = client.get_page(page_id)
    body: dict[str, Any] = {}
    properties = _update_properties(client, page, args)
    if properties:
        body["properties"] = properties
    icon = _icon(args.icon)
    if icon:
        body["icon"] = icon

    plan = Plan(summary=f"update page {page_id}")
    plan.add("PATCH", f"/pages/{page_id}", body)
    if not applying(args):
        emit_plan(plan, json_mode=json_mode(args))
        return
    updated = run_plan(client, plan)[0]
    if json_mode(args):
        emit_result(
            {
                "id": updated.get("id", page_id),
                "url": updated.get("url", ""),
                "title": props.page_title(updated),
                "updated": sorted(properties) + (["icon"] if icon else []),
            },
            json_mode=True,
        )
    else:
        emit_result(f"updated page {page_id}", json_mode=False)


# --------------------------------------------------------------------------
# page append
# --------------------------------------------------------------------------


def cmd_page_append(args: argparse.Namespace) -> None:
    page_id = parse_id(args.id, _ID_WHAT)
    blocks = _body_blocks(args)
    if not blocks:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="empty body: nothing to append",
            remediation="pass --body '<markdown>' or --body-file <path>",
        )
    after = parse_id(args.after, "block id") if args.after else None
    chunks = _chunks(blocks)
    plan = Plan(summary=f"append {len(blocks)} block(s) to {page_id}")
    append_plan(page_id, chunks, after, plan)
    if not applying(args):
        emit_plan(plan, json_mode=json_mode(args))
        return
    client = get_client(args)
    append_in_chunks(client, page_id, chunks, after)
    if json_mode(args):
        emit_result(
            {"id": page_id, "appended_blocks": len(blocks), "requests": len(chunks)},
            json_mode=True,
        )
    else:
        emit_result(f"appended {len(blocks)} blocks to {page_id}", json_mode=False)


# --------------------------------------------------------------------------
# page archive / restore
# --------------------------------------------------------------------------


def _trash(args: argparse.Namespace, *, in_trash: bool) -> None:
    page_id = parse_id(args.id, _ID_WHAT)
    verb = "archive" if in_trash else "restore"
    plan = Plan(summary=f"{verb} page {page_id}")
    plan.add("PATCH", f"/pages/{page_id}", {"in_trash": in_trash})
    if not applying(args):
        emit_plan(plan, json_mode=json_mode(args))
        return
    client = get_client(args)
    run_plan(client, plan)
    if json_mode(args):
        emit_result({"id": page_id, "in_trash": in_trash}, json_mode=True)
    else:
        emit_result(f"{verb}d page {page_id}", json_mode=False)


def cmd_page_archive(args: argparse.Namespace) -> None:
    return _trash(args, in_trash=True)


def cmd_page_restore(args: argparse.Namespace) -> None:
    return _trash(args, in_trash=False)


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------


def _add_set_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--set",
        action="append",
        metavar="NAME=VALUE",
        default=[],
        help="Set a property (repeatable). Needs a data source parent.",
    )


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "page",
        help="Read and write Notion pages (get/create/update/append/archive/restore).",
        description="Read and write Notion pages. Ids may be raw ids or Notion URLs.",
    )
    add_json_flag(p)
    p.set_defaults(func=noun_help(p), json=False)
    # parser_class must propagate or nested parse errors lose the error:/hint: contract.
    verbs = p.add_subparsers(dest="page_command", parser_class=type(p))

    get = verbs.add_parser("get", help="Read a page (properties + body as Markdown).")
    get.add_argument("id", help=_ID_HELP)
    get.add_argument("--no-content", action="store_true", help="Skip the page body.")
    get.add_argument("--depth", type=int, default=3, help="Block nesting depth (default 3).")
    get.add_argument("--raw", action="store_true", help="With --json, include the raw API objects.")
    add_json_flag(get)
    get.set_defaults(func=notion_command(cmd_page_get))

    create = verbs.add_parser("create", help="Create a page under a page or data source parent.")
    create.add_argument("--parent", required=True, help="Parent page / data source id or URL.")
    create.add_argument("--title", required=True, help="Page title.")
    add_body_flags(create)
    _add_set_flag(create)
    create.add_argument("--icon", help="Emoji icon for the new page.")
    add_apply_flag(create)
    add_json_flag(create)
    create.set_defaults(func=notion_command(cmd_page_create))

    update = verbs.add_parser("update", help="Update a page's title, properties or icon.")
    update.add_argument("id", help=_ID_HELP)
    update.add_argument("--title", help="New title.")
    _add_set_flag(update)
    update.add_argument("--icon", help="Emoji icon.")
    add_apply_flag(update)
    add_json_flag(update)
    update.set_defaults(func=notion_command(cmd_page_update))

    append = verbs.add_parser("append", help="Append Markdown content to a page.")
    append.add_argument("id", help=_ID_HELP)
    add_body_flags(append, required=True)
    append.add_argument("--after", help="Insert after this block id instead of at the end.")
    add_apply_flag(append)
    add_json_flag(append)
    append.set_defaults(func=notion_command(cmd_page_append))

    archive = verbs.add_parser("archive", help="Move a page to the trash (in_trash = true).")
    archive.add_argument("id", help=_ID_HELP)
    add_apply_flag(archive)
    add_json_flag(archive)
    archive.set_defaults(func=notion_command(cmd_page_archive))

    restore = verbs.add_parser("restore", help="Restore a page from the trash (in_trash = false).")
    restore.add_argument("id", help=_ID_HELP)
    add_apply_flag(restore)
    add_json_flag(restore)
    restore.set_defaults(func=notion_command(cmd_page_restore))
