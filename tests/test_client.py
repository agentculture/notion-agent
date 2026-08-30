"""Client layer: auth, throttling, retries, pagination — all through a fake transport."""

from __future__ import annotations

import pytest

from notion_agent.notion.client import (
    DEFAULT_VERSION,
    NotionClient,
    NotionError,
    Request,
    Response,
    token_from_env,
)
from tests.fake_notion import FakeNotion, listing


def _client(fake: FakeNotion, **kw) -> tuple[NotionClient, list[float]]:
    slept: list[float] = []
    clock = {"now": 0.0}

    def sleep(s: float) -> None:
        slept.append(s)
        clock["now"] += s

    client = NotionClient(
        "secret-xyz", transport=fake, sleep=sleep, clock=lambda: clock["now"], **kw
    )
    return client, slept


def test_token_from_env_prefers_api_key() -> None:
    assert token_from_env({"NOTION_API_KEY": "a", "NOTION_TOKEN": "b"}) == ("a", "NOTION_API_KEY")
    assert token_from_env({"NOTION_TOKEN": "b"}) == ("b", "NOTION_TOKEN")
    assert token_from_env({"NOTION_API_KEY": "  "}) is None
    assert token_from_env({}) is None


def test_headers_pin_version_and_bearer() -> None:
    fake = FakeNotion().on("GET", "/users/me", {"object": "user"})
    client, _ = _client(fake)
    client.me()
    headers = fake.headers_seen[0]
    assert headers["Authorization"] == "Bearer secret-xyz"
    assert headers["Notion-Version"] == DEFAULT_VERSION


def test_version_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTION_VERSION", "2022-06-28")
    assert NotionClient("t", transport=FakeNotion()).version == "2022-06-28"
    assert NotionClient("t", transport=FakeNotion(), version="x").version == "x"


def test_throttle_spaces_requests() -> None:
    fake = FakeNotion().on("GET", "/users/me", {"object": "user"})
    client, slept = _client(fake)
    client.me()
    client.me()
    client.me()
    # Two gaps of at least MIN_INTERVAL between three back-to-back calls.
    assert len(slept) == 2
    assert all(s >= 1 / 3 - 1e-9 for s in slept)


def test_429_retried_with_retry_after_on_post() -> None:
    attempts = {"n": 0}

    def handler(_req: Request) -> Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return Response(429, {"Retry-After": "2"}, {"code": "rate_limited", "message": "slow"})
        return Response(200, {}, {"object": "page", "id": "p"})

    fake = FakeNotion().on("POST", "/pages", handler)
    client, slept = _client(fake)
    assert client.request("POST", "/pages", body={})["id"] == "p"
    assert attempts["n"] == 2
    assert any(s >= 2 for s in slept)


def test_5xx_retried_only_for_get() -> None:
    seen = {"get": 0, "post": 0}

    def flaky_get(_req: Request) -> Response:
        seen["get"] += 1
        if seen["get"] == 1:
            return Response(503, {}, {"code": "service_unavailable", "message": "down"})
        return Response(200, {}, {"ok": True})

    def flaky_post(_req: Request) -> Response:
        seen["post"] += 1
        return Response(
            503, {}, {"code": "service_unavailable", "message": "down", "request_id": "r9"}
        )

    fake = FakeNotion().on("GET", "/x", flaky_get).on("POST", "/x", flaky_post)
    client, _ = _client(fake)
    assert client.request("GET", "/x") == {"ok": True}
    assert seen["get"] == 2
    with pytest.raises(NotionError) as exc:
        client.request("POST", "/x", body={})
    assert seen["post"] == 1
    assert exc.value.status == 503
    assert exc.value.request_id == "r9"


def test_gives_up_after_max_attempts() -> None:
    fake = FakeNotion().on(
        "GET", "/x", lambda _r: Response(429, {}, {"code": "rate_limited", "message": "no"})
    )
    client, _ = _client(fake, max_attempts=3)
    with pytest.raises(NotionError) as exc:
        client.request("GET", "/x")
    assert exc.value.code == "rate_limited"
    assert len(fake.calls) == 3


def test_error_carries_notion_fields() -> None:
    fake = FakeNotion().on(
        "GET",
        "/pages/p",
        (404, {"code": "object_not_found", "message": "nope", "request_id": "req-123"}),
    )
    client, _ = _client(fake)
    with pytest.raises(NotionError) as exc:
        client.get_page("p")
    err = exc.value
    assert (err.status, err.code, err.message, err.request_id) == (
        404,
        "object_not_found",
        "nope",
        "req-123",
    )
    assert "secret-xyz" not in str(err)


def test_non_json_error_body_is_wrapped() -> None:
    fake = FakeNotion().on("GET", "/x", lambda _r: Response(502, {}, {}))
    client, _ = _client(fake, max_attempts=1)
    with pytest.raises(NotionError) as exc:
        client.request("GET", "/x")
    assert exc.value.code == "http_502"


def test_paginate_get_follows_cursor() -> None:
    def handler(req: Request) -> dict:
        cursor = (req.query or {}).get("start_cursor")
        if cursor is None:
            return listing([{"n": 1}, {"n": 2}], has_more=True, cursor="c2")
        assert cursor == "c2"
        return listing([{"n": 3}])

    fake = FakeNotion().on("GET", "/blocks/b/children", handler)
    client, _ = _client(fake)
    assert [i["n"] for i in client.block_children("b")] == [1, 2, 3]
    assert fake.calls[0].query["page_size"] == 100


def test_paginate_post_puts_cursor_in_body_and_honours_limit() -> None:
    def handler(req: Request) -> dict:
        body = req.body or {}
        assert body["query"] == "plan"
        if "start_cursor" not in body:
            return listing([{"n": 1}, {"n": 2}], has_more=True, cursor="c2")
        return listing([{"n": 3}, {"n": 4}])

    fake = FakeNotion().on("POST", "/search", handler)
    client, _ = _client(fake)
    assert [i["n"] for i in client.search("plan", limit=3)] == [1, 2, 3]
    assert fake.calls[0].body["page_size"] == 3
    assert fake.calls[1].body["page_size"] == 1
    assert list(client.search("plan", limit=0)) == []


def test_block_tree_recurses_children() -> None:
    fake = FakeNotion()
    fake.on(
        "GET",
        "/blocks/root/children",
        listing([{"id": "a", "type": "bulleted_list_item", "has_children": True}]),
    )
    fake.on(
        "GET",
        "/blocks/a/children",
        listing([{"id": "b", "type": "paragraph", "has_children": False}]),
    )
    client, _ = _client(fake)
    tree = client.block_tree("root")
    assert tree[0]["children"][0]["id"] == "b"
    assert client.block_tree("root", depth=1)[0].get("children") is None
