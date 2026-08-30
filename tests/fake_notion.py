"""A fake Notion transport for tests — recorded-shape fixtures, no network.

``FakeNotion`` is a :data:`notion_agent.notion.client.Transport`: it matches
``(METHOD, path)`` against routes and records every request it receives so
tests can assert exactly which mutating calls were made (or not made — the
dry-run contract).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

from notion_agent.notion.client import Request, Response

Handler = Callable[[Request], Response | dict[str, Any] | tuple[int, dict[str, Any]]]

WORKSPACE_ID = "50b523dc-87bf-8143-8212-0003b5d974fa"
INTEGRATION_ID = "3cc523dc-87bf-8104-8b96-00272a53770d"
PAGE_ID = "3cb523dc-87bf-8062-9682-f5568590e1bd"
PARENT_PAGE_ID = "3cb523dc-87bf-8040-b790-d8f024cb2143"
DATABASE_ID = "3cb523dc-87bf-8023-9dc0-eb514862f88a"
DATA_SOURCE_ID = "3cb523dc-87bf-8061-b2f6-000b00a26b39"
BLOCK_ID = "3cc523dc-87bf-81da-b121-f5179d770d6e"
NEW_PAGE_ID = "3cc523dc-87bf-8137-87d0-d6fd92d7c940"


def rt(text: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": {"content": text, "link": None},
            "annotations": {
                "bold": False,
                "italic": False,
                "strikethrough": False,
                "underline": False,
                "code": False,
                "color": "default",
            },
            "plain_text": text,
            "href": None,
        }
    ]


def block(btype: str, text: str, block_id: str = BLOCK_ID, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"rich_text": rt(text), "color": "default"}
    payload.update(extra)
    return {
        "object": "block",
        "id": block_id,
        "type": btype,
        "has_children": False,
        "in_trash": False,
        "parent": {"type": "page_id", "page_id": PAGE_ID},
        btype: payload,
    }


def users_me(owner_type: str = "user") -> dict[str, Any]:
    owner: dict[str, Any] = {"type": owner_type}
    if owner_type == "user":
        owner["user"] = {"object": "user", "id": "u-1", "name": "Ori", "type": "person"}
    else:
        owner["workspace"] = True
    return {
        "object": "user",
        "id": INTEGRATION_ID,
        "name": "Spark",
        "type": "bot",
        "bot": {
            "owner": owner,
            "workspace_name": "Sparkrun",
            "workspace_id": WORKSPACE_ID,
        },
        "request_id": "req-me",
    }


def page(page_id: str = PAGE_ID, title: str = "Cross platform integration Plan") -> dict[str, Any]:
    return {
        "object": "page",
        "id": page_id,
        "created_time": "2026-08-29T21:07:00.000Z",
        "last_edited_time": "2026-08-29T21:07:00.000Z",
        "parent": {"type": "page_id", "page_id": PARENT_PAGE_ID},
        "in_trash": False,
        "url": f"https://app.notion.com/p/{page_id.replace('-', '')}",
        "properties": {
            "title": {"id": "title", "type": "title", "title": rt(title)},
        },
    }


def row_page(page_id: str = PAGE_ID) -> dict[str, Any]:
    return {
        "object": "page",
        "id": page_id,
        "parent": {
            "type": "data_source_id",
            "data_source_id": DATA_SOURCE_ID,
            "database_id": DATABASE_ID,
        },
        "in_trash": False,
        "url": f"https://app.notion.com/p/{page_id.replace('-', '')}",
        "properties": {
            "Project name": {"id": "title", "type": "title", "title": rt("Launch")},
            "Status": {"id": "s", "type": "status", "status": {"name": "In progress"}},
            "Priority": {"id": "p", "type": "select", "select": {"name": "High"}},
            "Team": {"id": "t", "type": "multi_select", "multi_select": [{"name": "Core"}]},
            "End date": {"id": "d", "type": "date", "date": {"start": "2026-09-01", "end": None}},
            "Progress": {
                "id": "f",
                "type": "formula",
                "formula": {"type": "number", "number": 0.5},
            },
        },
    }


def data_source() -> dict[str, Any]:
    return {
        "object": "data_source",
        "id": DATA_SOURCE_ID,
        "title": rt("Projects"),
        "parent": {"type": "database_id", "database_id": DATABASE_ID},
        "url": f"https://app.notion.com/p/{DATA_SOURCE_ID.replace('-', '')}",
        "in_trash": False,
        "properties": {
            "Project name": {"id": "title", "type": "title", "title": {}},
            "Status": {
                "id": "s",
                "type": "status",
                "status": {"options": [{"name": "Not started"}, {"name": "In progress"}]},
            },
            "Priority": {"id": "p", "type": "select", "select": {"options": [{"name": "High"}]}},
            "Team": {"id": "t", "type": "multi_select", "multi_select": {"options": []}},
            "End date": {"id": "d", "type": "date", "date": {}},
            "Progress": {"id": "f", "type": "formula", "formula": {"expression": "1"}},
        },
    }


def database(data_sources: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "object": "database",
        "id": DATABASE_ID,
        "title": rt("Projects"),
        "data_sources": (
            data_sources
            if data_sources is not None
            else [{"id": DATA_SOURCE_ID, "name": "Projects"}]
        ),
        "parent": {"type": "workspace", "workspace": True},
        "url": f"https://app.notion.com/p/{DATABASE_ID.replace('-', '')}",
    }


def listing(results: list[dict[str, Any]], *, has_more: bool = False, cursor: str | None = None):
    return {
        "object": "list",
        "results": results,
        "has_more": has_more,
        "next_cursor": cursor,
    }


def not_found(kind: str = "page", object_id: str = PAGE_ID) -> tuple[int, dict[str, Any]]:
    return 404, {
        "object": "error",
        "status": 404,
        "code": "object_not_found",
        "message": (
            f"Could not find {kind} with ID: {object_id}. Make sure the relevant pages and "
            'databases are shared with your integration "Spark".'
        ),
        "additional_data": {"integration_id": INTEGRATION_ID},
        "request_id": "req-123",
    }


class FakeNotion:
    """Route table + request recorder implementing the client ``Transport``."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, re.Pattern[str], Handler]] = []
        self.calls: list[Request] = []
        self.headers_seen: list[dict[str, str]] = []

    def on(
        self, method: str, path: str, handler: Handler | dict[str, Any] | tuple[int, dict]
    ) -> "FakeNotion":
        pattern = re.compile("^" + re.escape(path).replace("\\*", "[^/]+") + "$")
        if not callable(handler):
            fixed = handler
            # Deep-copy per call: the client mutates fetched blocks (attaches
            # children), and a shared fixture would leak between requests.
            handler = lambda _req: copy.deepcopy(fixed)  # noqa: E731
        key = (method.upper(), pattern.pattern)
        # A later registration for the same (method, path) replaces the
        # earlier one, so `.standard().on(...)` overrides work as expected.
        self.routes = [r for r in self.routes if (r[0], r[1].pattern) != key]
        self.routes.append((method.upper(), pattern, handler))
        return self

    def __call__(self, req: Request, headers: Any) -> Response:
        self.calls.append(req)
        self.headers_seen.append(dict(headers))
        for method, pattern, handler in self.routes:
            if method == req.method and pattern.match(req.path):
                result = handler(req)
                if isinstance(result, Response):
                    return result
                if isinstance(result, tuple):
                    status, body = result
                    return Response(status, {}, body)
                return Response(200, {}, result)
        return Response(
            404,
            {},
            {
                "object": "error",
                "status": 404,
                "code": "unrouted",
                "message": f"fake: no route for {req.method} {req.path}",
                "request_id": "req-unrouted",
            },
        )

    def mutations(self) -> list[Request]:
        return [
            c
            for c in self.calls
            if c.method != "GET" and not c.path.endswith("/query") and c.path != "/search"
        ]

    def standard(self) -> "FakeNotion":
        """The routes most CLI tests need."""
        self.on("GET", "/users/me", users_me())
        self.on("GET", f"/pages/{PAGE_ID}", page())
        self.on("GET", f"/pages/{PARENT_PAGE_ID}", page(PARENT_PAGE_ID, "Getting Started"))
        self.on("GET", f"/pages/{NEW_PAGE_ID}", page(NEW_PAGE_ID, "Created"))
        self.on(
            "GET",
            f"/blocks/{PAGE_ID}/children",
            listing([block("heading_1", "Background"), block("paragraph", "Context here", "b-2")]),
        )
        self.on("GET", f"/blocks/{BLOCK_ID}", block("paragraph", "Hello"))
        self.on("GET", f"/blocks/{BLOCK_ID}/children", listing([]))
        self.on("GET", f"/data_sources/{DATA_SOURCE_ID}", data_source())
        self.on("GET", f"/databases/{DATABASE_ID}", database())
        self.on("GET", f"/pages/{DATA_SOURCE_ID}", not_found("page", DATA_SOURCE_ID))
        self.on("GET", f"/pages/{DATABASE_ID}", not_found("page", DATABASE_ID))
        self.on("GET", f"/data_sources/{DATABASE_ID}", not_found("data source", DATABASE_ID))
        self.on("POST", f"/data_sources/{DATA_SOURCE_ID}/query", listing([row_page()]))
        self.on("POST", "/search", listing([page(), data_source()]))
        self.on("POST", "/pages", page(NEW_PAGE_ID, "Created"))
        self.on("PATCH", f"/pages/{PAGE_ID}", page())
        self.on("PATCH", "/blocks/*/children", lambda req: listing(req.body.get("children", [])))
        self.on("PATCH", f"/blocks/{BLOCK_ID}", block("paragraph", "Updated"))
        self.on("DELETE", f"/blocks/{BLOCK_ID}", block("paragraph", "Hello", in_trash=True))
        self.on("GET", "/comments", listing([]))
        self.on("POST", "/comments", {"object": "comment", "id": "cm-1", "rich_text": rt("hi")})
        return self
