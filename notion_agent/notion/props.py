"""Property values — flatten API shapes for reading, build payloads for writing.

Pure functions, no I/O. Two directions:

* :func:`flatten_properties` turns a page's ``properties`` object into plain
  scalars/lists an agent can read at a glance (``{"Status": "Done",
  "Tags": ["a", "b"]}``). The raw shape stays available via ``--raw``.
* :func:`build_properties` turns ``Name=value`` assignments into the typed
  payload the API expects, using the data source schema to pick the shape.
  Read-only property types (formula, rollup, created_*, …) are refused with a
  clear :class:`ValueError`.

Value syntax for ``--set``:

- ``multi_select`` / ``people`` / ``relation`` / ``files``: comma-separated.
- ``date``: ISO ``2026-08-30`` or ``2026-08-30T10:00:00Z``; a range as
  ``start/end``.
- ``checkbox``: ``true``/``false``/``yes``/``no``/``1``/``0``.
- ``number``: int or float.
- ``select`` / ``status``: the option name (created on the fly for select).
"""

from __future__ import annotations

from typing import Any

from notion_agent.notion.markdown import plain_text, rich_text

READ_ONLY_TYPES = frozenset(
    {
        "formula",
        "rollup",
        "created_time",
        "created_by",
        "last_edited_time",
        "last_edited_by",
        "unique_id",
        "verification",
        "button",
    }
)
_TRUE = {"true", "yes", "y", "1", "on", "checked"}
_FALSE = {"false", "no", "n", "0", "off", "unchecked", ""}


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------


def _user_label(user: dict[str, Any] | None) -> str:
    if not user:
        return ""
    return str(user.get("name") or user.get("id") or "")


def flatten_value(prop: dict[str, Any]) -> Any:
    """Reduce one property object to a plain Python value."""
    ptype = prop.get("type", "")
    value = prop.get(ptype)
    if ptype in ("title", "rich_text"):
        return plain_text(value)
    if ptype in ("select", "status"):
        return (value or {}).get("name") if value else None
    if ptype == "multi_select":
        return [opt.get("name") for opt in value or []]
    if ptype == "date":
        if not value:
            return None
        start, end = value.get("start"), value.get("end")
        return f"{start}/{end}" if end else start
    if ptype == "people":
        return [_user_label(u) for u in value or []]
    if ptype in ("created_by", "last_edited_by"):
        return _user_label(value)
    if ptype == "files":
        out = []
        for f in value or []:
            kind = f.get("type")
            url = (f.get(kind) or {}).get("url") if kind else None
            out.append(url or f.get("name"))
        return out
    if ptype == "relation":
        return [r.get("id") for r in value or []]
    if ptype == "formula":
        inner = value or {}
        return flatten_value(
            {"type": inner.get("type", ""), inner.get("type", ""): inner.get(inner.get("type", ""))}
        )
    if ptype == "rollup":
        inner = value or {}
        kind = inner.get("type", "")
        if kind == "array":
            return [flatten_value(item) for item in inner.get("array", [])]
        return inner.get(kind)
    if ptype == "unique_id":
        inner = value or {}
        prefix = inner.get("prefix")
        number = inner.get("number")
        return f"{prefix}-{number}" if prefix else number
    if ptype == "verification":
        return (value or {}).get("state")
    if ptype in ("string", "boolean", "number", "checkbox", "url", "email", "phone_number"):
        return value
    if ptype in ("created_time", "last_edited_time"):
        return value
    return value


def flatten_properties(properties: dict[str, Any]) -> dict[str, Any]:
    return {name: flatten_value(prop) for name, prop in (properties or {}).items()}


def title_property_name(properties: dict[str, Any]) -> str | None:
    for name, prop in (properties or {}).items():
        if prop.get("type") == "title":
            return name
    return None


def page_title(page: dict[str, Any]) -> str:
    """Best-effort title of a page / database / data source object."""
    if page.get("object") in ("database", "data_source"):
        return plain_text(page.get("title"))
    props = page.get("properties") or {}
    name = title_property_name(props)
    return plain_text(props[name].get("title")) if name else ""


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------


def parse_assignment(text: str) -> tuple[str, str]:
    """Split ``Name=value`` (first ``=`` wins so values may contain ``=``)."""
    name, sep, value = text.partition("=")
    if not sep or not name.strip():
        raise ValueError(f"expected Name=value, got {text!r}")
    return name.strip(), value.strip()


def _split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_value(ptype: str, value: str) -> dict[str, Any]:
    """Build the API payload for one property of type ``ptype``."""
    if ptype in READ_ONLY_TYPES:
        raise ValueError(f"property type '{ptype}' is read-only")
    if ptype == "title":
        return {"title": rich_text(value)}
    if ptype == "rich_text":
        return {"rich_text": rich_text(value)}
    if ptype == "number":
        if value == "":
            return {"number": None}
        try:
            number = int(value) if value.lstrip("-").isdigit() else float(value)
        except ValueError as err:
            raise ValueError(f"'{value}' is not a number") from err
        return {"number": number}
    if ptype == "select":
        return {"select": {"name": value} if value else None}
    if ptype == "status":
        return {"status": {"name": value}}
    if ptype == "multi_select":
        return {"multi_select": [{"name": v} for v in _split_list(value)]}
    if ptype == "checkbox":
        lowered = value.lower()
        if lowered in _TRUE:
            return {"checkbox": True}
        if lowered in _FALSE:
            return {"checkbox": False}
        raise ValueError(f"'{value}' is not a boolean (use true/false)")
    if ptype == "date":
        if not value:
            return {"date": None}
        start, _, end = value.partition("/")
        payload: dict[str, Any] = {"start": start}
        if end:
            payload["end"] = end
        return {"date": payload}
    if ptype in ("url", "email", "phone_number"):
        return {ptype: value or None}
    if ptype == "people":
        return {"people": [{"object": "user", "id": v} for v in _split_list(value)]}
    if ptype == "relation":
        return {"relation": [{"id": v} for v in _split_list(value)]}
    if ptype == "files":
        return {
            "files": [
                {"type": "external", "name": v.rsplit("/", 1)[-1] or v, "external": {"url": v}}
                for v in _split_list(value)
            ]
        }
    raise ValueError(f"unsupported property type '{ptype}'")


def resolve_property_name(schema: dict[str, Any], name: str) -> str:
    """Match a user-typed property name against the schema, case-insensitively."""
    if name in schema:
        return name
    lowered = {k.lower(): k for k in schema}
    if name.lower() in lowered:
        return lowered[name.lower()]
    raise ValueError(f"unknown property '{name}'; known: {', '.join(sorted(schema))}")


def build_properties(schema: dict[str, Any], assignments: list[str]) -> dict[str, Any]:
    """``["Status=Done", "Tags=a,b"]`` → typed ``properties`` payload."""
    out: dict[str, Any] = {}
    for assignment in assignments:
        name, value = parse_assignment(assignment)
        real = resolve_property_name(schema, name)
        ptype = schema[real].get("type", "")
        try:
            out[real] = build_value(ptype, value)
        except ValueError as err:
            raise ValueError(f"{real}: {err}") from err
    return out


def schema_summary(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact, agent-readable view of a data source's property schema."""
    rows = []
    for name, prop in (schema or {}).items():
        ptype = prop.get("type", "")
        row: dict[str, Any] = {
            "name": name,
            "type": ptype,
            "writable": ptype not in READ_ONLY_TYPES,
        }
        cfg = prop.get(ptype) or {}
        options = cfg.get("options") if isinstance(cfg, dict) else None
        if ptype == "status" and isinstance(cfg, dict):
            options = cfg.get("options")
        if options:
            row["options"] = [o.get("name") for o in options]
        if ptype == "relation" and isinstance(cfg, dict):
            row["target"] = cfg.get("data_source_id") or cfg.get("database_id")
        rows.append(row)
    return rows
