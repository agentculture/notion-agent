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


def _flat_date(value: Any) -> Any:
    if not value:
        return None
    start, end = value.get("start"), value.get("end")
    return f"{start}/{end}" if end else start


def _flat_files(value: Any) -> list[Any]:
    out = []
    for f in value or []:
        kind = f.get("type")
        url = (f.get(kind) or {}).get("url") if kind else None
        out.append(url or f.get("name"))
    return out


def _flat_formula(value: Any) -> Any:
    inner = value or {}
    kind = inner.get("type", "")
    return flatten_value({"type": kind, kind: inner.get(kind)})


def _flat_rollup(value: Any) -> Any:
    inner = value or {}
    kind = inner.get("type", "")
    if kind == "array":
        return [flatten_value(item) for item in inner.get("array", [])]
    return inner.get(kind)


def _flat_unique_id(value: Any) -> Any:
    inner = value or {}
    prefix, number = inner.get("prefix"), inner.get("number")
    return f"{prefix}-{number}" if prefix else number


_FLATTENERS: dict[str, Any] = {
    "title": plain_text,
    "rich_text": plain_text,
    "select": lambda v: (v or {}).get("name") if v else None,
    "status": lambda v: (v or {}).get("name") if v else None,
    "multi_select": lambda v: [opt.get("name") for opt in v or []],
    "date": _flat_date,
    "people": lambda v: [_user_label(u) for u in v or []],
    "created_by": _user_label,
    "last_edited_by": _user_label,
    "files": _flat_files,
    "relation": lambda v: [r.get("id") for r in v or []],
    "formula": _flat_formula,
    "rollup": _flat_rollup,
    "unique_id": _flat_unique_id,
    "verification": lambda v: (v or {}).get("state"),
}


def flatten_value(prop: dict[str, Any]) -> Any:
    """Reduce one property object to a plain Python value."""
    ptype = prop.get("type", "")
    value = prop.get(ptype)
    flattener = _FLATTENERS.get(ptype)
    # Scalars (number, checkbox, url, email, phone_number, timestamps, ...) pass through.
    return flattener(value) if flattener else value


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


def _build_number(value: str) -> dict[str, Any]:
    if value == "":
        return {"number": None}
    try:
        number = int(value) if value.lstrip("-").isdigit() else float(value)
    except ValueError as err:
        raise ValueError(f"'{value}' is not a number") from err
    return {"number": number}


def _build_checkbox(value: str) -> dict[str, Any]:
    lowered = value.lower()
    if lowered in _TRUE:
        return {"checkbox": True}
    if lowered in _FALSE:
        return {"checkbox": False}
    raise ValueError(f"'{value}' is not a boolean (use true/false)")


def _build_date(value: str) -> dict[str, Any]:
    if not value:
        return {"date": None}
    start, _, end = value.partition("/")
    payload: dict[str, Any] = {"start": start}
    if end:
        payload["end"] = end
    return {"date": payload}


def _build_files(value: str) -> dict[str, Any]:
    return {
        "files": [
            {"type": "external", "name": v.rsplit("/", 1)[-1] or v, "external": {"url": v}}
            for v in _split_list(value)
        ]
    }


_BUILDERS: dict[str, Any] = {
    "title": lambda v: {"title": rich_text(v)},
    "rich_text": lambda v: {"rich_text": rich_text(v)},
    "number": _build_number,
    "select": lambda v: {"select": {"name": v} if v else None},
    "status": lambda v: {"status": {"name": v}},
    "multi_select": lambda v: {"multi_select": [{"name": x} for x in _split_list(v)]},
    "checkbox": _build_checkbox,
    "date": _build_date,
    "url": lambda v: {"url": v or None},
    "email": lambda v: {"email": v or None},
    "phone_number": lambda v: {"phone_number": v or None},
    "people": lambda v: {"people": [{"object": "user", "id": x} for x in _split_list(v)]},
    "relation": lambda v: {"relation": [{"id": x} for x in _split_list(v)]},
    "files": _build_files,
}


def build_value(ptype: str, value: str) -> dict[str, Any]:
    """Build the API payload for one property of type ``ptype``."""
    if ptype in READ_ONLY_TYPES:
        raise ValueError(f"property type '{ptype}' is read-only")
    builder = _BUILDERS.get(ptype)
    if builder is None:
        raise ValueError(f"unsupported property type '{ptype}'")
    return builder(value)


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


SCHEMA_TYPES = frozenset(
    {
        "title",
        "rich_text",
        "number",
        "select",
        "multi_select",
        "status",
        "checkbox",
        "date",
        "url",
        "email",
        "phone_number",
        "people",
        "files",
        "relation",
    }
)


def build_schema(specs: list[str]) -> dict[str, Any]:
    """``["Name=title", "Kind=select:agent,human", "Rel=relation:<ds-id>"]`` → schema payload.

    The shape ``POST /databases`` expects under ``initial_data_source.properties``.
    Exactly one ``title`` property is required; when none is given a ``Name``
    title property is added so the database is always usable.
    """
    schema: dict[str, Any] = {}
    for spec in specs:
        name, value = parse_assignment(spec)
        ptype, _, extra = value.partition(":")
        ptype = ptype.strip().lower()
        if ptype not in SCHEMA_TYPES:
            raise ValueError(
                f"{name}: unsupported property type '{ptype}'; "
                f"known: {', '.join(sorted(SCHEMA_TYPES))}"
            )
        if name in schema:
            raise ValueError(f"duplicate property '{name}'")
        if ptype in ("select", "multi_select"):
            schema[name] = {ptype: {"options": [{"name": o} for o in _split_list(extra)]}}
        elif ptype == "relation":
            if not extra:
                raise ValueError(
                    f"{name}: relation needs a target, e.g. {name}=relation:<data-source-id>"
                )
            schema[name] = {"relation": {"data_source_id": extra.strip(), "single_property": {}}}
        elif ptype == "number":
            schema[name] = {"number": {"format": extra.strip() or "number"}}
        else:
            schema[name] = {ptype: {}}
    titles = [n for n, v in schema.items() if "title" in v]
    if len(titles) > 1:
        raise ValueError(f"only one title property is allowed (got {', '.join(titles)})")
    if not titles:
        schema = {"Name": {"title": {}}, **schema}
    return schema


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
