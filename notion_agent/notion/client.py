"""Zero-dependency Notion HTTP client: auth, versioning, rate limiting, pagination.

The whole client is ``urllib.request`` on top of the stdlib, so the runtime
package keeps ``dependencies = []``. Everything a verb needs to remember about
the wire protocol is centralised here:

* **Auth** — a bearer token, read from the environment by :func:`token_from_env`
  (``NOTION_API_KEY`` first, ``NOTION_TOKEN`` as the fallback). The token is
  injectable (``NotionClient(token=...)``) so a different secret source (e.g.
  ``grant``) can be wired in without touching the verbs.
* **Version** — every request pins ``Notion-Version`` to :data:`DEFAULT_VERSION`
  (``2026-03-11``, the current latest). Override with ``NOTION_VERSION`` only
  when you know what you are doing: the verbs are written against this
  version's shapes (``data_sources``, ``in_trash``, ``position``).
* **Rate limiting** — Notion allows ~3 requests/second per integration.
  :meth:`NotionClient.request` throttles to :data:`MIN_INTERVAL` between calls
  and honours ``Retry-After`` on ``429`` with exponential backoff + jitter, up
  to :data:`MAX_ATTEMPTS`. Transient ``5xx`` responses are retried the same way.
* **Pagination** — :meth:`NotionClient.paginate` walks ``has_more`` /
  ``next_cursor`` for both ``GET`` (query-string cursor) and ``POST``
  (body cursor) list endpoints and yields items until the optional ``limit``.

The transport is a plain callable ``(Request, headers) -> Response`` so tests
inject recorded fixtures instead of hitting the live API.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

API_BASE = "https://api.notion.com/v1"
DEFAULT_VERSION = "2026-03-11"
TOKEN_ENV_VARS = ("NOTION_API_KEY", "NOTION_TOKEN")
VERSION_ENV_VAR = "NOTION_VERSION"
MIN_INTERVAL = 1.0 / 3.0
MAX_ATTEMPTS = 6
MAX_PAGE_SIZE = 100
TIMEOUT_SECONDS = 30


@dataclass
class Request:
    """One API call, before headers are attached."""

    method: str
    path: str
    body: dict[str, Any] | None = None
    query: dict[str, Any] | None = None

    def url(self) -> str:
        url = API_BASE + self.path
        if self.query:
            url += "?" + urllib.parse.urlencode(
                {k: v for k, v in self.query.items() if v is not None}
            )
        return url


@dataclass
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)

    def header(self, name: str) -> str | None:
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return None


Transport = Callable[[Request, Mapping[str, str]], Response]


class NotionError(Exception):
    """A non-2xx response (or a network failure) from the Notion API."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        request_id: str | None = None,
        request: Request | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id
        self.request = request

    @classmethod
    def from_response(cls, resp: Response, request: Request | None = None) -> "NotionError":
        body = resp.body if isinstance(resp.body, dict) else {}
        return cls(
            resp.status,
            str(body.get("code") or f"http_{resp.status}"),
            str(body.get("message") or f"HTTP {resp.status}"),
            request_id=body.get("request_id"),
            request=request,
        )


def urllib_transport(req: Request, headers: Mapping[str, str]) -> Response:
    """The live transport: one HTTPS round-trip via ``urllib``."""
    data = json.dumps(req.body).encode("utf-8") if req.body is not None else None
    http_req = urllib.request.Request(
        req.url(), data=data, method=req.method, headers=dict(headers)
    )
    try:
        with urllib.request.urlopen(http_req, timeout=TIMEOUT_SECONDS) as resp:  # nosec B310
            raw = resp.read()
            return Response(resp.status, dict(resp.headers.items()), _decode(raw, resp.status))
    except urllib.error.HTTPError as err:
        raw = err.read()
        return Response(err.code, dict(err.headers.items()), _decode(raw, err.code))
    except urllib.error.URLError as err:
        raise NotionError(
            0, "network_error", f"could not reach api.notion.com: {err.reason}"
        ) from err
    except TimeoutError as err:
        raise NotionError(0, "network_error", "request to api.notion.com timed out") from err


def _decode(raw: bytes, status: int) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {
            "object": "error",
            "status": status,
            "code": f"http_{status}",
            "message": raw.decode("utf-8", errors="replace")[:500],
        }
    return parsed if isinstance(parsed, dict) else {"results": parsed}


def token_from_env(environ: Mapping[str, str] | None = None) -> tuple[str, str] | None:
    """Return ``(token, env_var_name)`` for the first set token variable, or ``None``."""
    env = os.environ if environ is None else environ
    for name in TOKEN_ENV_VARS:
        value = env.get(name, "").strip()
        if value:
            return value, name
    return None


class NotionClient:
    """Thin, throttled, retrying wrapper over the Notion REST API."""

    def __init__(
        self,
        token: str,
        *,
        version: str | None = None,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        min_interval: float = MIN_INTERVAL,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.token = token
        self.version = version or os.environ.get(VERSION_ENV_VAR, "").strip() or DEFAULT_VERSION
        self._transport = transport or urllib_transport
        self._sleep = sleep
        self._clock = clock
        self._min_interval = min_interval
        self._max_attempts = max(1, max_attempts)
        self._last_request_at: float | None = None
        self.request_count = 0

    # -- plumbing ---------------------------------------------------------

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.version,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "notion-agent (+https://github.com/agentculture/notion-agent)",
        }

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = self._clock() - self._last_request_at
            if elapsed < self._min_interval:
                self._sleep(self._min_interval - elapsed)
        self._last_request_at = self._clock()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform one API call, throttled and retried; return the decoded body."""
        req = Request(method.upper(), path, body, query)
        last: Response | None = None
        for attempt in range(self._max_attempts):
            self._throttle()
            self.request_count += 1
            resp = self._transport(req, self.headers())
            last = resp
            if resp.status < 400:
                return resp.body
            # 429 means the server did not process the request, so any method
            # is safe to replay. A 5xx may have landed server-side, so only
            # idempotent GETs are retried — a write that got a 5xx is reported
            # (with its request_id) rather than risk a duplicate create.
            retryable = resp.status == 429 or (resp.status >= 500 and req.method == "GET")
            if not retryable or attempt == self._max_attempts - 1:
                raise NotionError.from_response(resp, req)
            self._sleep(self._retry_delay(resp, attempt))
        raise NotionError.from_response(last or Response(0), req)  # pragma: no cover - defensive

    @staticmethod
    def _retry_delay(resp: Response, attempt: int) -> float:
        retry_after = resp.header("Retry-After")
        base = 0.5 * (2**attempt)
        if retry_after:
            try:
                base = max(base, float(retry_after))
            except ValueError:
                pass
        return base + random.uniform(0, 0.25)  # nosec B311 - jitter, not crypto

    def paginate(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield every item of a paginated list endpoint (up to ``limit``)."""
        if limit is not None and limit <= 0:
            return
        cursor: str | None = None
        yielded = 0
        while True:
            page_size = MAX_PAGE_SIZE if limit is None else min(MAX_PAGE_SIZE, limit - yielded)
            data = self._list_page(method, path, body, query, cursor, page_size)
            for item in data.get("results", []):
                yield item
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            cursor = data.get("next_cursor") if data.get("has_more") else None
            if not cursor:
                return

    def _list_page(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        query: dict[str, Any] | None,
        cursor: str | None,
        page_size: int,
    ) -> dict[str, Any]:
        """One page of a list endpoint; GET carries the cursor in the query, POST in the body."""
        paging: dict[str, Any] = {"page_size": page_size}
        if cursor:
            paging["start_cursor"] = cursor
        if method.upper() == "GET":
            return self.request(method, path, query={**(query or {}), **paging})
        return self.request(method, path, body={**(body or {}), **paging}, query=query)

    # -- convenience wrappers (one per endpoint family) -------------------

    def me(self) -> dict[str, Any]:
        return self.request("GET", "/users/me")

    def get_page(self, page_id: str) -> dict[str, Any]:
        return self.request("GET", f"/pages/{page_id}")

    def get_block(self, block_id: str) -> dict[str, Any]:
        return self.request("GET", f"/blocks/{block_id}")

    def get_database(self, database_id: str) -> dict[str, Any]:
        return self.request("GET", f"/databases/{database_id}")

    def get_data_source(self, data_source_id: str) -> dict[str, Any]:
        return self.request("GET", f"/data_sources/{data_source_id}")

    def block_children(
        self, block_id: str, *, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        return self.paginate("GET", f"/blocks/{block_id}/children", limit=limit)

    def block_tree(self, block_id: str, *, depth: int = 3) -> list[dict[str, Any]]:
        """Fetch children recursively; nested children land under ``"children"``."""
        blocks = list(self.block_children(block_id))
        if depth > 1:
            for block in blocks:
                if block.get("has_children") and block.get("type") not in (
                    "child_page",
                    "child_database",
                ):
                    block["children"] = self.block_tree(block["id"], depth=depth - 1)
        return blocks

    def search(
        self,
        query: str = "",
        *,
        kind: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        body: dict[str, Any] = {}
        if query:
            body["query"] = query
        if kind:
            body["filter"] = {"property": "object", "value": kind}
        return self.paginate("POST", "/search", body=body, limit=limit)

    def query_data_source(
        self,
        data_source_id: str,
        *,
        filter: dict[str, Any] | None = None,  # noqa: A002 - mirrors the API field name
        sorts: list[dict[str, Any]] | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        body: dict[str, Any] = {}
        if filter:
            body["filter"] = filter
        if sorts:
            body["sorts"] = sorts
        return self.paginate(
            "POST", f"/data_sources/{data_source_id}/query", body=body, limit=limit
        )

    def list_comments(self, block_id: str, *, limit: int | None = None) -> Iterator[dict[str, Any]]:
        return self.paginate("GET", "/comments", query={"block_id": block_id}, limit=limit)
