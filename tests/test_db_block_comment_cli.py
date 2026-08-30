"""The db / block / comment noun groups, driven through a fake Notion transport.

The three modules are parsed by a standalone parser (they are wired into
``_build_parser`` in a later task), but dispatched through the real
:func:`notion_agent.cli._dispatch` so the exception → exit-code contract, the
stdout/stderr split, and the dry-run contract are all exercised for real.
"""

from __future__ import annotations

import json

import pytest

from notion_agent.cli import _CliArgumentParser, _dispatch
from notion_agent.cli._commands import _common, block, comment, db
from notion_agent.notion.client import NotionClient
from tests.fake_notion import (
    BLOCK_ID,
    DATA_SOURCE_ID,
    DATABASE_ID,
    NEW_PAGE_ID,
    PAGE_ID,
    FakeNotion,
)
from tests.fake_notion import block as block_fixture
from tests.fake_notion import (
    database,
    listing,
    not_found,
    row_page,
    rt,
)


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeNotion:
    transport = FakeNotion().standard()
    monkeypatch.setattr(
        _common,
        "build_client",
        lambda: NotionClient("secret-xyz", transport=transport, sleep=lambda s: None),
    )
    return transport


def run(argv: list[str]) -> int:
    parser = _CliArgumentParser(prog="notion-agent")
    _CliArgumentParser._json_hint = "--json" in argv
    sub = parser.add_subparsers(dest="command", parser_class=_CliArgumentParser)
    db.register(sub)
    block.register(sub)
    comment.register(sub)
    args = parser.parse_args(argv)
    return _dispatch(args)


def with_client(monkeypatch: pytest.MonkeyPatch, transport: FakeNotion) -> FakeNotion:
    """Install ``transport`` as the CLI's client.

    A later ``.on()`` for the same method+path replaces the earlier route, so
    overrides go *after* ``standard()``.
    """
    monkeypatch.setattr(
        _common,
        "build_client",
        lambda: NotionClient("secret-xyz", transport=transport, sleep=lambda s: None),
    )
    return transport


# --------------------------------------------------------------------------
# 1. db get + data source resolution
# --------------------------------------------------------------------------


def test_db_get_resolves_a_database_id_to_its_single_data_source(fake, capsys) -> None:
    assert run(["db", "get", DATABASE_ID]) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert "# Projects" in out.out
    assert f"id: {DATA_SOURCE_ID}" in out.out
    assert f"database_id: {DATABASE_ID}" in out.out
    assert "Status  status" in out.out
    assert "options: Not started, In progress" in out.out
    assert "[read-only]" in out.out  # the formula property


def test_db_get_json_carries_the_schema_summary(fake, capsys) -> None:
    assert run(["db", "get", DATA_SOURCE_ID, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == DATA_SOURCE_ID
    names = {row["name"]: row for row in payload["properties"]}
    assert names["Progress"]["writable"] is False
    assert names["Project name"]["type"] == "title"


def test_db_get_on_a_multi_source_database_lists_the_choices(monkeypatch, capsys) -> None:
    with_client(
        monkeypatch,
        FakeNotion()
        .standard()
        .on(
            "GET",
            f"/databases/{DATABASE_ID}",
            database(data_sources=[{"id": "a" * 32, "name": "A"}, {"id": "b" * 32, "name": "B"}]),
        ),
    )
    assert run(["db", "get", DATABASE_ID]) == 1
    err = capsys.readouterr().err
    assert "a" * 32 in err and "b" * 32 in err
    assert err.startswith("error:") and "hint:" in err


# --------------------------------------------------------------------------
# 2. db query
# --------------------------------------------------------------------------


def _query_body(fake: FakeNotion) -> dict:
    return [c.body for c in fake.calls if c.path.endswith("/query")][-1]


def test_db_query_where_builds_a_typed_filter(fake, capsys) -> None:
    assert run(["db", "query", DATA_SOURCE_ID, "--where", "Status=In progress"]) == 0
    assert _query_body(fake)["filter"] == {
        "property": "Status",
        "status": {"equals": "In progress"},
    }
    assert "Launch" in capsys.readouterr().out


def test_db_query_two_where_clauses_are_anded(fake, capsys) -> None:
    assert (
        run(
            [
                "db",
                "query",
                DATA_SOURCE_ID,
                "--where",
                "Status=Done",
                "--where",
                "Team=Core",
            ]
        )
        == 0
    )
    conditions = _query_body(fake)["filter"]["and"]
    assert conditions[0] == {"property": "Status", "status": {"equals": "Done"}}
    assert conditions[1] == {"property": "Team", "multi_select": {"contains": "Core"}}


def test_db_query_sort_and_limit(fake, capsys) -> None:
    assert run(["db", "query", DATA_SOURCE_ID, "--sort", "Priority:desc", "--limit", "10"]) == 0
    body = _query_body(fake)
    assert body["sorts"] == [{"property": "Priority", "direction": "descending"}]
    assert body["page_size"] == 10


def test_db_query_json_is_a_list_of_flattened_rows(fake, capsys) -> None:
    assert run(["db", "query", DATA_SOURCE_ID, "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert isinstance(rows, list)
    assert rows[0]["title"] == "Launch"
    assert rows[0]["properties"]["Status"] == "In progress"


def test_db_query_raw_filter_passes_through(fake, capsys) -> None:
    raw = '{"property": "Status", "status": {"equals": "Done"}}'
    assert run(["db", "query", DATA_SOURCE_ID, "--filter", raw]) == 0
    assert _query_body(fake)["filter"] == json.loads(raw)


def test_db_query_rejects_where_with_filter(fake, capsys) -> None:
    code = run(["db", "query", DATA_SOURCE_ID, "--where", "Status=Done", "--filter", "{}"])
    assert code == 1
    assert "mutually exclusive" in capsys.readouterr().err


def test_db_query_filter_file(fake, capsys, tmp_path) -> None:
    path = tmp_path / "f.json"
    path.write_text('{"property": "Team", "multi_select": {"contains": "Core"}}')
    assert run(["db", "query", DATA_SOURCE_ID, "--filter-file", str(path)]) == 0
    assert _query_body(fake)["filter"]["property"] == "Team"


# --------------------------------------------------------------------------
# 3. db row create
# --------------------------------------------------------------------------


def test_db_row_create_dry_run_sends_nothing(fake, capsys) -> None:
    code = run(["db", "row", "create", DATA_SOURCE_ID, "--title", "Launch", "--set", "Status=Done"])
    assert code == 0
    assert fake.mutations() == []
    out = capsys.readouterr()
    assert out.out.startswith("dry-run:")
    assert "re-run with --apply" in out.out
    payload = json.loads([line for line in out.out.splitlines() if line.startswith("  {")][0])
    assert payload["parent"]["data_source_id"] == DATA_SOURCE_ID
    assert payload["properties"]["Project name"]["title"][0]["text"]["content"] == "Launch"
    assert payload["properties"]["Status"]["status"]["name"] == "Done"


def test_db_row_create_apply_posts_once(fake, capsys) -> None:
    code = run(
        [
            "db",
            "row",
            "create",
            DATA_SOURCE_ID,
            "--title",
            "Launch",
            "--set",
            "Status=Done",
            "--apply",
        ]
    )
    assert code == 0
    mutations = fake.mutations()
    assert len(mutations) == 1
    assert (mutations[0].method, mutations[0].path) == ("POST", "/pages")
    assert f"created row {NEW_PAGE_ID}" in capsys.readouterr().out


def test_db_row_create_with_body_puts_blocks_in_children(fake, capsys) -> None:
    assert (
        run(["db", "row", "create", DATA_SOURCE_ID, "--title", "L", "--body", "# Hi", "--apply"])
        == 0
    )
    body = [c.body for c in fake.calls if c.path == "/pages"][0]
    assert body["children"][0]["type"] == "heading_1"


def test_db_row_create_refuses_a_read_only_property(fake, capsys) -> None:
    assert run(["db", "row", "create", DATA_SOURCE_ID, "--set", "Progress=1"]) == 1
    err = capsys.readouterr().err
    assert "Progress" in err and "read-only" in err
    assert fake.mutations() == []


# --------------------------------------------------------------------------
# 4. db row update
# --------------------------------------------------------------------------


def test_db_row_update_refuses_a_non_row_page(fake, capsys) -> None:
    assert run(["db", "row", "update", PAGE_ID, "--set", "Status=Done"]) == 1
    assert "not a database row" in capsys.readouterr().err


def test_db_row_update_patches_only_the_given_properties(monkeypatch, capsys) -> None:
    transport = with_client(
        monkeypatch, FakeNotion().standard().on("GET", f"/pages/{PAGE_ID}", row_page())
    )
    assert run(["db", "row", "update", PAGE_ID, "--set", "Status=Done", "--apply"]) == 0
    mutations = transport.mutations()
    assert len(mutations) == 1
    assert (mutations[0].method, mutations[0].path) == ("PATCH", f"/pages/{PAGE_ID}")
    assert list(mutations[0].body["properties"]) == ["Status"]


# --------------------------------------------------------------------------
# 5. block writes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["block", "delete", BLOCK_ID],
        ["block", "restore", BLOCK_ID],
        ["block", "append", PAGE_ID, "--body", "hello"],
        ["block", "update", BLOCK_ID, "--text", "hello"],
    ],
)
def test_block_writes_are_dry_run_by_default(fake, capsys, argv) -> None:
    assert run(argv) == 0
    assert fake.mutations() == []
    assert capsys.readouterr().out.startswith("dry-run:")


def test_block_delete_apply(fake, capsys) -> None:
    assert run(["block", "delete", BLOCK_ID, "--apply"]) == 0
    mutations = fake.mutations()
    assert [(m.method, m.path) for m in mutations] == [("DELETE", f"/blocks/{BLOCK_ID}")]


def test_block_restore_apply(fake, capsys) -> None:
    assert run(["block", "restore", BLOCK_ID, "--apply"]) == 0
    mutations = fake.mutations()
    assert [(m.method, m.path) for m in mutations] == [("PATCH", f"/blocks/{BLOCK_ID}")]
    assert mutations[0].body == {"in_trash": False}


def test_block_append_after_uses_position(fake, capsys) -> None:
    assert run(["block", "append", PAGE_ID, "--body", "hello", "--after", BLOCK_ID, "--apply"]) == 0
    mutations = fake.mutations()
    assert len(mutations) == 1
    assert mutations[0].path == f"/blocks/{PAGE_ID}/children"
    assert mutations[0].body["position"] == {
        "type": "after_block",
        "after_block": {"id": BLOCK_ID},
    }
    assert "after" not in mutations[0].body


def test_block_update_patches_rich_text(fake, capsys) -> None:
    assert run(["block", "update", BLOCK_ID, "--text", "**bold** text", "--apply"]) == 0
    mutations = fake.mutations()
    assert len(mutations) == 1
    spans = mutations[0].body["paragraph"]["rich_text"]
    assert spans[0]["annotations"]["bold"] is True
    assert "".join(s["text"]["content"] for s in spans) == "bold text"


def test_block_update_refuses_a_divider(monkeypatch, capsys) -> None:
    divider = block_fixture("paragraph", "x")
    divider["type"] = "divider"
    divider.pop("paragraph")
    divider["divider"] = {}
    transport = with_client(
        monkeypatch, FakeNotion().standard().on("GET", f"/blocks/{BLOCK_ID}", divider)
    )
    assert run(["block", "update", BLOCK_ID, "--text", "hi", "--apply"]) == 1
    err = capsys.readouterr().err
    assert "divider" in err and "hint:" in err
    assert transport.mutations() == []


# --------------------------------------------------------------------------
# 6. block reads
# --------------------------------------------------------------------------


def test_block_children_renders_markdown(fake, capsys) -> None:
    assert run(["block", "children", PAGE_ID]) == 0
    out = capsys.readouterr()
    assert "# Background" in out.out
    assert out.err == ""


def test_block_get_json(fake, capsys) -> None:
    assert run(["block", "get", BLOCK_ID, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "paragraph"
    assert payload["markdown"] == "Hello"
    assert payload["has_children"] is False


# --------------------------------------------------------------------------
# 7. comments
# --------------------------------------------------------------------------


def test_comment_list_empty(fake, capsys) -> None:
    assert run(["comment", "list", PAGE_ID]) == 0
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == ""


def test_comment_list_renders_author_and_text(monkeypatch, capsys) -> None:
    one = {
        "object": "comment",
        "id": "cm-1",
        "discussion_id": "d1",
        "created_time": "2026-08-30T10:00:00.000Z",
        "created_by": {"object": "user", "id": "u-1", "name": "Ori"},
        "rich_text": rt("hi"),
    }
    with_client(monkeypatch, FakeNotion().standard().on("GET", "/comments", listing([one])))
    assert run(["comment", "list", PAGE_ID]) == 0
    line = capsys.readouterr().out.strip()
    assert "Ori" in line and "hi" in line and "2026-08-30" in line


def test_comment_add_dry_run_then_apply(fake, capsys) -> None:
    assert run(["comment", "add", PAGE_ID, "--body", "hi"]) == 0
    assert fake.mutations() == []
    assert run(["comment", "add", PAGE_ID, "--body", "hi", "--apply"]) == 0
    mutations = fake.mutations()
    assert len(mutations) == 1
    assert (mutations[0].method, mutations[0].path) == ("POST", "/comments")
    assert mutations[0].body["parent"] == {"page_id": PAGE_ID}
    assert "added comment cm-1" in capsys.readouterr().out


def test_comment_add_into_a_discussion_has_no_parent(fake, capsys) -> None:
    assert run(["comment", "add", PAGE_ID, "--body", "hi", "--discussion", "d1", "--apply"]) == 0
    body = fake.mutations()[0].body
    assert body["discussion_id"] == "d1"
    assert "parent" not in body


# --------------------------------------------------------------------------
# 8. parse errors under every nested subparser
# --------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [["db"], ["db", "row"], ["block"], ["comment"]])
def test_bare_nouns_print_help(fake, capsys, argv) -> None:
    assert run(argv) == 0
    out = capsys.readouterr()
    assert "usage:" in out.out
    assert out.err == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["db", "row", "create"],
        ["block", "bogus"],
        ["comment", "add", PAGE_ID],
        ["db", "query", DATA_SOURCE_ID, "--bogus"],
    ],
)
def test_parse_errors_use_the_structured_contract(fake, capsys, argv) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run(argv)
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


# --------------------------------------------------------------------------
# 9. the token never leaks
# --------------------------------------------------------------------------


def test_failures_name_sharing_and_request_id_but_never_the_token(monkeypatch, capsys) -> None:
    with_client(
        monkeypatch,
        FakeNotion().standard().on("GET", f"/blocks/{BLOCK_ID}", not_found("block", BLOCK_ID)),
    )
    assert run(["block", "get", BLOCK_ID]) == 1
    out = capsys.readouterr()
    assert "shared" in out.err and "req-123" in out.err
    assert "secret-xyz" not in out.err
    assert "secret-xyz" not in out.out


# --------------------------------------------------------------------------
# db create
# --------------------------------------------------------------------------


def test_db_create_is_dry_run_by_default(fake, capsys) -> None:
    assert (
        run(
            [
                "db",
                "create",
                "--parent",
                PAGE_ID,
                "--title",
                "Agents db",
                "--prop",
                "Kind=select:agent",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert out.startswith("dry-run:") and "POST /databases" in out
    assert fake.mutations() == []


def test_db_create_apply_posts_databases(monkeypatch, capsys) -> None:
    fake = with_client(
        monkeypatch,
        FakeNotion()
        .standard()
        .on(
            "POST",
            "/databases",
            {
                "object": "database",
                "id": DATABASE_ID,
                "data_sources": [{"id": DATA_SOURCE_ID, "name": "Agents db"}],
                "url": "https://app.notion.com/p/x",
            },
        ),
    )
    rc = run(
        [
            "db",
            "create",
            "--parent",
            PAGE_ID,
            "--title",
            "Agents db",
            "--prop",
            "Kind=select:agent,human",
            "--prop",
            "Active=checkbox",
            "--apply",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data_source_id"] == DATA_SOURCE_ID
    (req,) = fake.mutations()
    assert req.method == "POST" and req.path == "/databases"
    assert req.body["parent"] == {"type": "page_id", "page_id": PAGE_ID}
    props_sent = req.body["initial_data_source"]["properties"]
    assert list(props_sent) == ["Name", "Kind", "Active"]
    assert props_sent["Kind"]["select"]["options"][1] == {"name": "human"}


def test_db_create_rejects_bad_prop_spec(fake, capsys) -> None:
    assert run(["db", "create", "--parent", PAGE_ID, "--title", "x", "--prop", "F=formula"]) == 1
    assert "unsupported property type" in capsys.readouterr().err
