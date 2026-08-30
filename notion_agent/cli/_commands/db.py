"""``notion-agent db`` — data sources: schema, queries, and rows.

Under the 2025-09-03 data model a *database* is a container of one or more
*data sources*; the schema and the query endpoint both live on the data source.
Every ``<id>`` these verbs take is therefore resolved through
:func:`~notion_agent.cli._commands._common.resolve_data_source`, which accepts a
data source id directly, resolves a single-source database id to its one data
source, and refuses (exit 1, listing the choices) a database with several.

Verbs:

* ``db get`` — the schema view (properties, types, options, read-only flags).
* ``db query`` — rows, with ``--where Prop=value`` sugar that builds the typed
  filter from the schema, or a raw ``--filter`` / ``--filter-file`` JSON escape
  hatch.
* ``db row create`` / ``db row update`` — writes, dry-run unless ``--apply``.
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
    resolve_data_source,
    to_cli_error,
)
from notion_agent.cli._errors import EXIT_USER_ERROR, CliError
from notion_agent.cli._output import emit_result
from notion_agent.notion import props
from notion_agent.notion.client import NotionError
from notion_agent.notion.markdown import BLOCKS_PER_REQUEST, chunk_blocks, markdown_to_blocks

DEFAULT_LIMIT = 50

_EQUALS_TYPES = ("select", "status", "date")
_CONTAINS_TYPES = ("multi_select", "title", "rich_text", "people", "relation")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _add_raw_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument("--raw", action="store_true", help="Emit the raw Notion API payload.")


def _emit_raw(payload: Any, *, json_mode_on: bool) -> None:
    emit_result(payload if json_mode_on else json.dumps(payload, indent=2), json_mode=json_mode_on)


def _clause(name: str, ptype: str, value: str) -> dict[str, Any]:
    """One ``--where Prop=value`` clause, typed from the schema."""
    if ptype in _EQUALS_TYPES:
        return {"property": name, ptype: {"equals": value}}
    if ptype in _CONTAINS_TYPES:
        return {"property": name, ptype: {"contains": value}}
    if ptype == "checkbox":
        checked = props.build_value("checkbox", value)["checkbox"]
        return {"property": name, "checkbox": {"equals": checked}}
    if ptype == "number":
        number = props.build_value("number", value)["number"]
        return {"property": name, "number": {"equals": number}}
    if ptype in ("url", "email", "phone_number"):
        return {"property": name, ptype: {"equals": value}}
    raise ValueError(
        f"cannot build a --where filter for property '{name}' of type '{ptype}'; "
        "use --filter with raw Notion filter JSON"
    )


def _where_filter(schema: dict[str, Any], wheres: list[str]) -> dict[str, Any] | None:
    clauses = []
    for where in wheres:
        name, value = props.parse_assignment(where)
        real = props.resolve_property_name(schema, name)
        clauses.append(_clause(real, schema[real].get("type", ""), value))
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"and": clauses}


def _sorts(schema: dict[str, Any], specs: list[str]) -> list[dict[str, Any]]:
    out = []
    for spec in specs:
        name, sep, direction = spec.rpartition(":")
        if not sep:
            name, direction = direction, "asc"
        direction = direction.strip().lower() or "asc"
        if direction in ("asc", "ascending"):
            resolved = "ascending"
        elif direction in ("desc", "descending"):
            resolved = "descending"
        else:
            raise ValueError(f"unknown sort direction '{direction}' (use asc or desc)")
        out.append(
            {
                "property": props.resolve_property_name(schema, name.strip()),
                "direction": resolved,
            }
        )
    return out


def _explicit_filter(args: argparse.Namespace) -> dict[str, Any] | None:
    raw = getattr(args, "filter", None)
    path = getattr(args, "filter_file", None)
    if path is not None:
        try:
            with open(path, encoding="utf-8") as handle:
                raw = handle.read()
        except OSError as err:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"cannot read {path}: {err.strerror or err}",
                remediation="check the path and permissions",
            ) from err
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"--filter is not valid JSON: {err}",
            remediation="pass a Notion filter object, e.g. "
            '\'{"property": "Status", "status": {"equals": "Done"}}\'',
        ) from err
    if not isinstance(parsed, dict):
        raise CliError(
            code=EXIT_USER_ERROR,
            message="--filter must be a JSON object (a Notion filter)",
            remediation='e.g. \'{"property": "Status", "status": {"equals": "Done"}}\'',
        )
    return parsed


def _title_value(schema: dict[str, Any], title: str) -> tuple[str, dict[str, Any]]:
    name = props.title_property_name(schema)
    if name is None:
        raise ValueError("this data source has no title property; use --set instead of --title")
    return name, props.build_value("title", title)


def _row_line(page: dict[str, Any]) -> str:
    properties = page.get("properties") or {}
    title_name = props.title_property_name(properties)
    flat = props.flatten_properties(properties)
    title = flat.get(title_name, "") if title_name else ""
    rest = []
    for name, value in flat.items():
        if name == title_name:
            continue
        rest.append(f"{name}={_scalar(value)}")
    return "\t".join([page.get("id", ""), str(title or ""), " ".join(rest)])


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(v) for v in value if v is not None)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# --------------------------------------------------------------------------
# db get
# --------------------------------------------------------------------------


@notion_command
def cmd_get(args: argparse.Namespace) -> int:
    client = get_client(args)
    source = resolve_data_source(client, parse_id(args.id, "data source or database id"))
    schema = source.get("properties") or {}
    summary = props.schema_summary(schema)
    as_json = json_mode(args)
    if args.raw and not as_json:
        _emit_raw(source, json_mode_on=False)
        return 0
    parent = source.get("parent") or {}
    payload = {
        "id": source.get("id"),
        "title": props.page_title(source),
        "database_id": parent.get("database_id"),
        "url": source.get("url"),
        "properties": summary,
    }
    if as_json:
        if args.raw:
            payload["raw"] = source
        emit_result(payload, json_mode=True)
        return 0
    lines = [f"# {payload['title']}", f"id: {payload['id']}"]
    if payload["database_id"]:
        lines.append(f"database_id: {payload['database_id']}")
    if payload["url"]:
        lines.append(f"url: {payload['url']}")
    lines.append("properties:")
    for row in summary:
        line = f"  {row['name']}  {row['type']}"
        if row.get("options"):
            line += "  options: " + ", ".join(str(o) for o in row["options"])
        if not row.get("writable", True):
            line += "  [read-only]"
        lines.append(line)
    emit_result("\n".join(lines), json_mode=False)
    return 0


# --------------------------------------------------------------------------
# db query
# --------------------------------------------------------------------------


@notion_command
def cmd_query(args: argparse.Namespace) -> int:
    client = get_client(args)
    source = resolve_data_source(client, parse_id(args.id, "data source or database id"))
    schema = source.get("properties") or {}
    wheres = args.where or []
    explicit = _explicit_filter(args)
    if wheres and explicit is not None:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="--where and --filter/--filter-file are mutually exclusive",
            remediation="use --where for schema-typed sugar or --filter for raw filter JSON",
        )
    query_filter = explicit if explicit is not None else _where_filter(schema, wheres)
    sorts = _sorts(schema, args.sort or [])
    rows = list(
        client.query_data_source(source["id"], filter=query_filter, sorts=sorts, limit=args.limit)
    )
    as_json = json_mode(args)
    if args.raw:
        _emit_raw(rows, json_mode_on=as_json)
        return 0
    if as_json:
        emit_result(
            [
                {
                    "id": row.get("id"),
                    "url": row.get("url"),
                    "title": props.page_title(row),
                    "properties": props.flatten_properties(row.get("properties") or {}),
                }
                for row in rows
            ],
            json_mode=True,
        )
        return 0
    if not rows:
        return 0
    emit_result("\n".join(_row_line(row) for row in rows), json_mode=False)
    return 0


# --------------------------------------------------------------------------
# db row create / update
# --------------------------------------------------------------------------


@notion_command
def cmd_row_create(args: argparse.Namespace) -> int:
    client = get_client(args)
    source = resolve_data_source(client, parse_id(args.id, "data source or database id"))
    schema = source.get("properties") or {}
    payload = props.build_properties(schema, args.set or [])
    if args.title is not None:
        name, value = _title_value(schema, args.title)
        payload[name] = value
    body: dict[str, Any] = {
        "parent": {"data_source_id": source["id"]},
        "properties": payload,
    }
    markdown = read_body(args)
    chunks: list[list[dict[str, Any]]] = []
    if markdown:
        chunks = chunk_blocks(markdown_to_blocks(markdown), BLOCKS_PER_REQUEST)
        body["children"] = chunks[0]

    plan = Plan(f"create a row in data source {source['id']}")
    plan.add("POST", "/pages", body, describe="create the row")
    for index, chunk in enumerate(chunks[1:], start=2):
        plan.add(
            "PATCH",
            "/blocks/<new-page-id>/children",
            {"children": chunk},
            describe=f"append body chunk {index}",
        )
    if not applying(args):
        emit_plan(plan, json_mode=json_mode(args))
        return 0

    created = client.request("POST", "/pages", body=body)
    page_id = created.get("id", "")
    for chunk in chunks[1:]:
        try:
            client.request("PATCH", f"/blocks/{page_id}/children", body={"children": chunk})
        except NotionError as err:
            cli_err = to_cli_error(err)
            raise CliError(
                code=cli_err.code,
                message=f"row {page_id} was created but its body is incomplete: {cli_err.message}",
                remediation=f"append the rest with 'notion-agent block append {page_id}'",
            ) from err
    if json_mode(args):
        emit_result({"id": page_id, "url": created.get("url")}, json_mode=True)
    else:
        emit_result(f"created row {page_id}\n{created.get('url', '')}", json_mode=False)
    return 0


@notion_command
def cmd_row_update(args: argparse.Namespace) -> int:
    client = get_client(args)
    page_id = parse_id(args.id, "page id")
    page = client.get_page(page_id)
    parent = page.get("parent") or {}
    data_source_id = parent.get("data_source_id")
    if not data_source_id:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"page {page_id} is not a database row (parent: {parent.get('type', '?')})",
            remediation="use 'notion-agent page update' for a standalone page",
        )
    schema = (client.get_data_source(data_source_id).get("properties")) or {}
    payload = props.build_properties(schema, args.set or [])
    if args.title is not None:
        name, value = _title_value(schema, args.title)
        payload[name] = value
    if not payload:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="nothing to update",
            remediation="pass --set Name=value (repeatable) and/or --title",
        )
    plan = Plan(f"update {len(payload)} propert{'y' if len(payload) == 1 else 'ies'} on {page_id}")
    plan.add("PATCH", f"/pages/{page_id}", {"properties": payload})
    if not applying(args):
        emit_plan(plan, json_mode=json_mode(args))
        return 0
    updated = client.request("PATCH", f"/pages/{page_id}", body={"properties": payload})
    if json_mode(args):
        emit_result({"id": updated.get("id", page_id), "url": updated.get("url")}, json_mode=True)
    else:
        emit_result(f"updated row {page_id}", json_mode=False)
    return 0


# --------------------------------------------------------------------------
# registration
# --------------------------------------------------------------------------


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("db", help="Databases and data sources: schema, queries, rows.")
    add_json_flag(p)
    p.set_defaults(func=noun_help(p), json=False)
    noun = p.add_subparsers(dest="db_command", parser_class=type(p))

    get = noun.add_parser("get", help="Show a data source's schema.")
    get.add_argument("id", help="Data source id, database id, or Notion URL.")
    add_json_flag(get)
    _add_raw_flag(get)
    get.set_defaults(func=cmd_get)

    query = noun.add_parser("query", help="Query rows of a data source.")
    query.add_argument("id", help="Data source id, database id, or Notion URL.")
    query.add_argument(
        "--where",
        action="append",
        metavar="PROP=VALUE",
        help="Schema-typed filter clause; repeatable (clauses are ANDed).",
    )
    query.add_argument("--filter", help="Raw Notion filter JSON (excludes --where).")
    query.add_argument("--filter-file", help="Read the raw filter JSON from a file.")
    query.add_argument(
        "--sort",
        action="append",
        metavar="PROP[:asc|desc]",
        help="Sort by a property; repeatable.",
    )
    query.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help=f"Max rows (default {DEFAULT_LIMIT})."
    )
    add_json_flag(query)
    _add_raw_flag(query)
    query.set_defaults(func=cmd_query)

    row = noun.add_parser("row", help="Create and update rows (pages in a data source).")
    add_json_flag(row)
    row.set_defaults(func=noun_help(row), json=False)
    row_sub = row.add_subparsers(dest="db_row_command", parser_class=type(p))

    create = row_sub.add_parser("create", help="Create a row.")
    create.add_argument("id", help="Data source id, database id, or Notion URL.")
    create.add_argument("--title", help="Value for the data source's title property.")
    create.add_argument(
        "--set",
        action="append",
        metavar="PROP=VALUE",
        help="Set a property; repeatable.",
    )
    add_body_flags(create)
    add_apply_flag(create)
    add_json_flag(create)
    create.set_defaults(func=cmd_row_create)

    update = row_sub.add_parser("update", help="Update a row's properties.")
    update.add_argument("id", help="Row (page) id or Notion URL.")
    update.add_argument("--title", help="New value for the title property.")
    update.add_argument(
        "--set",
        action="append",
        metavar="PROP=VALUE",
        help="Set a property; repeatable.",
    )
    add_apply_flag(update)
    add_json_flag(update)
    update.set_defaults(func=cmd_row_update)
