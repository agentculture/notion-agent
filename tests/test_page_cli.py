"""``search`` and ``page`` noun groups — dry-run contract, errors, chunked creates.

The nouns are not wired into ``_build_parser`` yet (that is a later task), so
these tests build a standalone parser with the same ``_CliArgumentParser`` /
``parser_class`` shape ``main()`` uses, and dispatch through the real
``_dispatch`` so exception→exit-code translation is exercised for real.
"""

from __future__ import annotations

import json

import pytest

from notion_agent.cli import _CliArgumentParser, _dispatch
from notion_agent.cli._commands import _common, page, search
from notion_agent.notion.client import NotionClient
from tests.fake_notion import (
    BLOCK_ID,
    DATA_SOURCE_ID,
    DATABASE_ID,
    NEW_PAGE_ID,
    PAGE_ID,
    PARENT_PAGE_ID,
    FakeNotion,
    listing,
)

TOKEN = "secret-xyz"


@pytest.fixture
def fake() -> FakeNotion:
    return FakeNotion().standard()


def run(argv: list[str], fake: FakeNotion, monkeypatch: pytest.MonkeyPatch) -> int:
    """Parse + dispatch ``argv`` against a fake transport; returns the exit code."""
    monkeypatch.setattr(
        _common,
        "build_client",
        lambda: NotionClient(TOKEN, transport=fake, sleep=lambda s: None),
    )
    _CliArgumentParser._json_hint = "--json" in argv
    parser = _CliArgumentParser(prog="notion-agent")
    sub = parser.add_subparsers(dest="command", parser_class=_CliArgumentParser)
    search.register(sub)
    page.register(sub)
    args = parser.parse_args(argv)
    return _dispatch(args)


# --------------------------------------------------------------------------
# 1. the dry-run contract: no --apply → nothing is sent
# --------------------------------------------------------------------------

DRY_RUN_CASES = {
    "create": ["page", "create", "--parent", PARENT_PAGE_ID, "--title", "Notes", "--body", "hi"],
    "update": ["page", "update", PAGE_ID, "--title", "Renamed"],
    "append": ["page", "append", PAGE_ID, "--body", "more"],
    "archive": ["page", "archive", PAGE_ID],
    "restore": ["page", "restore", PAGE_ID],
}


@pytest.mark.parametrize("argv", DRY_RUN_CASES.values(), ids=list(DRY_RUN_CASES))
def test_write_verbs_are_dry_run_by_default(argv, fake, monkeypatch, capsys) -> None:
    rc = run(list(argv), fake, monkeypatch)
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("dry-run:")
    assert "--apply" in out
    assert fake.mutations() == []


@pytest.mark.parametrize("argv", DRY_RUN_CASES.values(), ids=list(DRY_RUN_CASES))
def test_write_verbs_dry_run_json_is_one_document(argv, fake, monkeypatch, capsys) -> None:
    rc = run([*argv, "--json"], fake, monkeypatch)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["dry_run"] is True
    assert payload["requests"]
    assert fake.mutations() == []


def test_dry_run_plan_never_shows_headers_or_token(fake, monkeypatch, capsys) -> None:
    run(
        ["page", "create", "--parent", PARENT_PAGE_ID, "--title", "N", "--body", "hi"],
        fake,
        monkeypatch,
    )
    captured = capsys.readouterr()
    assert TOKEN not in captured.out
    assert TOKEN not in captured.err
    assert "Authorization" not in captured.out


# --------------------------------------------------------------------------
# 1b. --apply sends exactly the expected mutating requests
# --------------------------------------------------------------------------


def test_page_create_apply_posts_once(fake, monkeypatch, capsys) -> None:
    rc = run(
        [
            "page",
            "create",
            "--parent",
            PARENT_PAGE_ID,
            "--title",
            "Notes",
            "--body",
            "hello",
            "--apply",
        ],
        fake,
        monkeypatch,
    )
    out = capsys.readouterr().out
    assert rc == 0
    mutations = fake.mutations()
    assert [(m.method, m.path) for m in mutations] == [("POST", "/pages")]
    body = mutations[0].body
    assert body["parent"] == {"page_id": PARENT_PAGE_ID}
    assert body["properties"]["title"]["title"][0]["text"]["content"] == "Notes"
    assert len(body["children"]) == 1
    assert out.startswith(f"created page {NEW_PAGE_ID}")


def test_page_update_apply_patches_page(fake, monkeypatch, capsys) -> None:
    rc = run(["page", "update", PAGE_ID, "--title", "Renamed", "--apply"], fake, monkeypatch)
    assert rc == 0
    mutations = fake.mutations()
    assert [(m.method, m.path) for m in mutations] == [("PATCH", f"/pages/{PAGE_ID}")]
    title = mutations[0].body["properties"]["title"]["title"][0]["text"]["content"]
    assert title == "Renamed"
    assert capsys.readouterr().out.strip() == f"updated page {PAGE_ID}"


def test_page_update_requires_a_change(fake, monkeypatch, capsys) -> None:
    rc = run(["page", "update", PAGE_ID], fake, monkeypatch)
    err = capsys.readouterr().err
    assert rc == 1
    assert err.startswith("error: nothing to update")
    assert "hint:" in err
    assert fake.mutations() == []


def test_page_update_set_needs_a_data_source_parent(fake, monkeypatch, capsys) -> None:
    rc = run(["page", "update", PAGE_ID, "--set", "Status=Done"], fake, monkeypatch)
    err = capsys.readouterr().err
    assert rc == 1
    assert "data source parent" in err
    assert fake.mutations() == []


def test_page_append_apply_uses_after_block_position(fake, monkeypatch, capsys) -> None:
    rc = run(
        ["page", "append", PAGE_ID, "--body", "one\n\ntwo", "--after", BLOCK_ID, "--apply"],
        fake,
        monkeypatch,
    )
    assert rc == 0
    mutations = fake.mutations()
    assert [(m.method, m.path) for m in mutations] == [("PATCH", f"/blocks/{PAGE_ID}/children")]
    body = mutations[0].body
    assert len(body["children"]) == 2
    assert body["position"] == {"type": "after_block", "after_block": {"id": BLOCK_ID}}
    assert "after" not in body
    assert capsys.readouterr().out.strip() == f"appended 2 blocks to {PAGE_ID}"


def test_page_archive_and_restore_use_in_trash(fake, monkeypatch, capsys) -> None:
    assert run(["page", "archive", PAGE_ID, "--apply"], fake, monkeypatch) == 0
    assert run(["page", "restore", PAGE_ID, "--apply"], fake, monkeypatch) == 0
    capsys.readouterr()
    mutations = fake.mutations()
    assert [(m.method, m.path) for m in mutations] == [
        ("PATCH", f"/pages/{PAGE_ID}"),
        ("PATCH", f"/pages/{PAGE_ID}"),
    ]
    assert mutations[0].body == {"in_trash": True}
    assert mutations[1].body == {"in_trash": False}
    assert "archived" not in json.dumps(mutations[0].body)


# --------------------------------------------------------------------------
# 2 + 3. errors: not-shared 404, request_id, no token leak
# --------------------------------------------------------------------------


def test_not_found_names_the_integration_and_request_id(fake, monkeypatch, capsys) -> None:
    rc = run(["page", "get", DATABASE_ID], fake, monkeypatch)
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "shared" in captured.err
    assert "Spark" in captured.err
    assert "req-123" in captured.err
    assert captured.err.startswith("error: ")
    assert "hint:" in captured.err
    assert TOKEN not in captured.err


def test_not_found_json_error_is_one_document(fake, monkeypatch, capsys) -> None:
    rc = run(["page", "get", DATABASE_ID, "--json"], fake, monkeypatch)
    captured = capsys.readouterr()
    assert rc == 1
    payload = json.loads(captured.err)
    assert payload["code"] == 1
    assert "shared" in payload["message"]
    assert "Spark" in payload["message"]
    assert "req-123" in payload["message"]
    assert TOKEN not in captured.err
    assert TOKEN not in captured.out


def test_invalid_id_is_a_user_error(fake, monkeypatch, capsys) -> None:
    rc = run(["page", "get", "not-an-id"], fake, monkeypatch)
    err = capsys.readouterr().err
    assert rc == 1
    assert err.startswith("error: invalid page id")
    assert "hint:" in err


# --------------------------------------------------------------------------
# 4. >100-block create: one POST + follow-up appends; failure names the page
# --------------------------------------------------------------------------

BIG_BODY = "\n\n".join(f"paragraph {i}" for i in range(150))


def test_large_create_splits_into_create_plus_append(fake, monkeypatch, capsys) -> None:
    rc = run(
        [
            "page",
            "create",
            "--parent",
            PARENT_PAGE_ID,
            "--title",
            "Big",
            "--body",
            BIG_BODY,
            "--apply",
            "--json",
        ],
        fake,
        monkeypatch,
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    mutations = fake.mutations()
    assert [(m.method, m.path) for m in mutations] == [
        ("POST", "/pages"),
        ("PATCH", f"/blocks/{NEW_PAGE_ID}/children"),
    ]
    assert len(mutations[0].body["children"]) == 100
    assert len(mutations[1].body["children"]) == 50
    assert payload["id"] == NEW_PAGE_ID
    assert payload["appended_blocks"] == 150


def test_large_create_dry_run_names_the_unknown_page_id(fake, monkeypatch, capsys) -> None:
    rc = run(
        [
            "page",
            "create",
            "--parent",
            PARENT_PAGE_ID,
            "--title",
            "Big",
            "--body",
            BIG_BODY,
            "--json",
        ],
        fake,
        monkeypatch,
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert fake.mutations() == []
    assert payload["requests"][1]["path"] == "/blocks/<new-page-id>/children"
    assert "page id known after create" in payload["requests"][1]["describe"]


def test_failed_follow_up_append_names_the_created_page(monkeypatch, capsys) -> None:
    broken = FakeNotion()
    broken.on(
        "PATCH",
        f"/blocks/{NEW_PAGE_ID}/children",
        (
            500,
            {
                "object": "error",
                "status": 500,
                "code": "internal_server_error",
                "message": "boom",
                "request_id": "r5",
            },
        ),
    )
    broken.standard()
    rc = run(
        [
            "page",
            "create",
            "--parent",
            PARENT_PAGE_ID,
            "--title",
            "Big",
            "--body",
            BIG_BODY,
            "--apply",
        ],
        broken,
        monkeypatch,
    )
    captured = capsys.readouterr()
    assert rc != 0
    assert NEW_PAGE_ID in captured.err
    assert "was created but appending blocks failed" in captured.err
    assert f"page append {NEW_PAGE_ID}" in captured.err
    assert "r5" in captured.err
    assert TOKEN not in captured.err


# --------------------------------------------------------------------------
# 5. parent resolution: page parent vs data source parent
# --------------------------------------------------------------------------


def test_create_with_data_source_parent_builds_typed_properties(fake, monkeypatch, capsys) -> None:
    rc = run(
        [
            "page",
            "create",
            "--parent",
            DATA_SOURCE_ID,
            "--title",
            "Launch",
            "--set",
            "Status=In progress",
            "--json",
        ],
        fake,
        monkeypatch,
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    body = payload["requests"][0]["body"]
    assert body["parent"] == {"data_source_id": DATA_SOURCE_ID}
    assert body["properties"]["Status"]["status"]["name"] == "In progress"
    # The data source's title property is "Project name", not "title".
    assert body["properties"]["Project name"]["title"][0]["text"]["content"] == "Launch"
    assert fake.mutations() == []


def test_create_with_page_parent_uses_title_property(fake, monkeypatch, capsys) -> None:
    rc = run(
        ["page", "create", "--parent", PAGE_ID, "--title", "Child", "--json"],
        fake,
        monkeypatch,
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    body = payload["requests"][0]["body"]
    assert body["parent"] == {"page_id": PAGE_ID}
    assert body["properties"]["title"]["title"][0]["text"]["content"] == "Child"


def test_create_set_with_page_parent_is_a_user_error(fake, monkeypatch, capsys) -> None:
    rc = run(
        ["page", "create", "--parent", PAGE_ID, "--title", "Child", "--set", "Status=Done"],
        fake,
        monkeypatch,
    )
    err = capsys.readouterr().err
    assert rc == 1
    assert "properties other than title need a data source parent" in err
    assert fake.mutations() == []


def test_create_accepts_a_notion_url_as_parent(fake, monkeypatch, capsys) -> None:
    url = f"https://www.notion.so/Getting-Started-{PARENT_PAGE_ID.replace('-', '')}"
    rc = run(["page", "create", "--parent", url, "--title", "N", "--json"], fake, monkeypatch)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["requests"][0]["body"]["parent"] == {"page_id": PARENT_PAGE_ID}


# --------------------------------------------------------------------------
# 6. search
# --------------------------------------------------------------------------


def test_search_json_lists_pages_and_data_sources(fake, monkeypatch, capsys) -> None:
    rc = run(["search", "plan", "--json"], fake, monkeypatch)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert [row["object"] for row in payload] == ["page", "data_source"]
    assert payload[0]["id"] == PAGE_ID
    assert payload[0]["title"] == "Cross platform integration Plan"
    assert payload[1]["title"] == "Projects"
    assert fake.calls[0].body["query"] == "plan"


def test_search_text_is_tab_separated(fake, monkeypatch, capsys) -> None:
    rc = run(["search", "plan"], fake, monkeypatch)
    lines = capsys.readouterr().out.strip().split("\n")
    assert rc == 0
    assert len(lines) == 2
    assert lines[0].split("\t")[:3] == ["page", PAGE_ID, "Cross platform integration Plan"]


def test_search_data_sources_filter_uses_the_2025_09_03_value(fake, monkeypatch, capsys) -> None:
    run(["search", "--data-sources"], fake, monkeypatch)
    capsys.readouterr()
    assert fake.calls[0].body["filter"] == {"property": "object", "value": "data_source"}
    run(["search", "--pages"], fake, monkeypatch)
    capsys.readouterr()
    assert fake.calls[1].body["filter"] == {"property": "object", "value": "page"}


def test_search_raw_emits_api_objects(fake, monkeypatch, capsys) -> None:
    rc = run(["search", "--json", "--raw"], fake, monkeypatch)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload[0]["properties"]["title"]["type"] == "title"


def test_search_with_no_results_is_empty_and_succeeds(monkeypatch, capsys) -> None:
    empty = FakeNotion().on(
        "POST", "/search", {"object": "list", "results": [], "has_more": False, "next_cursor": None}
    )
    rc = run(["search", "nothing"], empty, monkeypatch)
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert captured.err == ""


# --------------------------------------------------------------------------
# 7. parse errors route through the structured contract
# --------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [["page", "get"], ["page", "bogus"], ["page", "get", "--nope"]])
def test_parse_errors_exit_one_with_error_and_hint(argv, fake, monkeypatch, capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run(argv, fake, monkeypatch)
    err = capsys.readouterr().err
    assert excinfo.value.code == 1
    assert err.startswith("error: ")
    assert "hint:" in err


def test_parse_error_json_mode_is_structured(fake, monkeypatch, capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run(["page", "bogus", "--json"], fake, monkeypatch)
    payload = json.loads(capsys.readouterr().err)
    assert excinfo.value.code == 1
    assert payload["code"] == 1
    assert payload["remediation"]


def test_bare_page_noun_prints_help(fake, monkeypatch, capsys) -> None:
    rc = run(["page"], fake, monkeypatch)
    out = capsys.readouterr().out
    assert rc == 0
    assert "usage:" in out
    assert "create" in out


# --------------------------------------------------------------------------
# 8. page get
# --------------------------------------------------------------------------


def test_page_get_json_carries_markdown(fake, monkeypatch, capsys) -> None:
    rc = run(["page", "get", PAGE_ID, "--json"], fake, monkeypatch)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 0
    assert payload["id"] == PAGE_ID
    assert payload["title"] == "Cross platform integration Plan"
    assert "# Background" in payload["markdown"]
    assert payload["in_trash"] is False
    assert payload["properties"]["title"] == "Cross platform integration Plan"
    assert "raw" not in payload
    assert captured.err == ""


def test_page_get_raw_includes_the_api_objects(fake, monkeypatch, capsys) -> None:
    run(["page", "get", PAGE_ID, "--json", "--raw"], fake, monkeypatch)
    payload = json.loads(capsys.readouterr().out)
    assert payload["raw"]["page"]["object"] == "page"
    assert payload["raw"]["blocks"][0]["type"] == "heading_1"


def test_page_get_text_layout(fake, monkeypatch, capsys) -> None:
    rc = run(["page", "get", PAGE_ID], fake, monkeypatch)
    out = capsys.readouterr().out
    assert rc == 0
    lines = out.split("\n")
    assert lines[0] == "# Cross platform integration Plan"
    assert lines[1] == f"id: {PAGE_ID}"
    assert lines[3] == f"parent: page_id {PARENT_PAGE_ID}"
    assert lines[4] == "in_trash: false"
    assert lines[5] == "properties:"
    assert "# Background" in out


def test_page_get_no_content_skips_the_body(fake, monkeypatch, capsys) -> None:
    rc = run(["page", "get", PAGE_ID, "--no-content", "--json"], fake, monkeypatch)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["markdown"] == ""
    assert all(not c.path.endswith("/children") for c in fake.calls)


def _ids_for_children(prefix: str):
    """A PATCH children handler that hands every created block an id."""
    counter = {"n": 0}

    def handler(req):
        out = []
        for child in req.body.get("children", []):
            counter["n"] += 1
            out.append({**child, "id": f"{prefix}-{counter['n']}"})
        return listing(out)

    return handler


def test_page_append_after_threads_position_through_every_chunk(monkeypatch, capsys) -> None:
    fake = FakeNotion().standard().on("PATCH", "/blocks/*/children", _ids_for_children("new"))
    body = "\n\n".join(f"p{i}" for i in range(150))
    rc = run(
        ["page", "append", PAGE_ID, "--body", body, "--after", BLOCK_ID, "--apply", "--json"],
        fake,
        monkeypatch,
    )
    assert rc == 0
    patches = [c for c in fake.mutations() if c.path == f"/blocks/{PAGE_ID}/children"]
    assert len(patches) == 2
    assert patches[0].body["position"]["after_block"]["id"] == BLOCK_ID
    # The second chunk lands right after the last block the first chunk created.
    assert patches[1].body["position"]["after_block"]["id"] == "new-100"


def test_page_append_dry_run_shows_positioned_follow_up_chunks(fake, capsys) -> None:
    body = "\n\n".join(f"p{i}" for i in range(101))
    assert (
        run(["page", "append", PAGE_ID, "--body", body, "--after", BLOCK_ID, "--json"], fake) == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["requests"][0]["body"]["position"]["after_block"]["id"] == BLOCK_ID
    assert "previous chunk" in payload["requests"][1]["describe"]
    assert fake.mutations() == []
