"""Property values: flattening for reads, typed payloads for writes."""

from __future__ import annotations

import pytest

from notion_agent.notion.props import (
    build_properties,
    build_schema,
    build_value,
    flatten_properties,
    page_title,
    parse_assignment,
    schema_summary,
)
from tests.fake_notion import data_source, page, row_page


def test_flatten_row() -> None:
    flat = flatten_properties(row_page()["properties"])
    assert flat == {
        "Project name": "Launch",
        "Status": "In progress",
        "Priority": "High",
        "Team": ["Core"],
        "End date": "2026-09-01",
        "Progress": 0.5,
    }


def test_flatten_misc_types() -> None:
    props = {
        "d": {"type": "date", "date": {"start": "a", "end": "b"}},
        "n": {"type": "date", "date": None},
        "p": {"type": "people", "people": [{"name": "Ori"}, {"id": "u2"}]},
        "f": {"type": "files", "files": [{"type": "external", "external": {"url": "http://f"}}]},
        "r": {"type": "relation", "relation": [{"id": "x"}]},
        "u": {"type": "unique_id", "unique_id": {"prefix": "T", "number": 7}},
        "ro": {"type": "rollup", "rollup": {"type": "number", "number": 3}},
        "ra": {
            "type": "rollup",
            "rollup": {"type": "array", "array": [{"type": "select", "select": {"name": "A"}}]},
        },
        "cb": {"type": "created_by", "created_by": {"name": "Bot"}},
        "c": {"type": "checkbox", "checkbox": True},
        "s": {"type": "select", "select": None},
        "v": {"type": "verification", "verification": {"state": "verified"}},
    }
    assert flatten_properties(props) == {
        "d": "a/b",
        "n": None,
        "p": ["Ori", "u2"],
        "f": ["http://f"],
        "r": ["x"],
        "u": "T-7",
        "ro": 3,
        "ra": ["A"],
        "cb": "Bot",
        "c": True,
        "s": None,
        "v": "verified",
    }


def test_page_title_for_page_and_data_source() -> None:
    assert page_title(page()) == "Cross platform integration Plan"
    assert page_title(row_page()) == "Launch"
    assert page_title(data_source()) == "Projects"
    assert page_title({"object": "page", "properties": {}}) == ""


def test_parse_assignment() -> None:
    assert parse_assignment("Status=In progress") == ("Status", "In progress")
    assert parse_assignment("Url=http://x?a=b") == ("Url", "http://x?a=b")
    with pytest.raises(ValueError):
        parse_assignment("no-equals")


@pytest.mark.parametrize(
    ("ptype", "value", "expected"),
    [
        ("title", "T", {"title": [{"type": "text", "text": {"content": "T", "link": None}}]}),
        ("number", "3", {"number": 3}),
        ("number", "-2.5", {"number": -2.5}),
        ("number", "", {"number": None}),
        ("select", "High", {"select": {"name": "High"}}),
        ("select", "", {"select": None}),
        ("status", "Done", {"status": {"name": "Done"}}),
        ("multi_select", "a, b", {"multi_select": [{"name": "a"}, {"name": "b"}]}),
        ("checkbox", "yes", {"checkbox": True}),
        ("checkbox", "0", {"checkbox": False}),
        ("date", "2026-09-01", {"date": {"start": "2026-09-01"}}),
        ("date", "2026-09-01/2026-09-02", {"date": {"start": "2026-09-01", "end": "2026-09-02"}}),
        ("date", "", {"date": None}),
        ("url", "http://x", {"url": "http://x"}),
        ("email", "", {"email": None}),
        (
            "people",
            "u1,u2",
            {"people": [{"object": "user", "id": "u1"}, {"object": "user", "id": "u2"}]},
        ),
        ("relation", "p1", {"relation": [{"id": "p1"}]}),
        (
            "files",
            "http://h/a.png",
            {
                "files": [
                    {"type": "external", "name": "a.png", "external": {"url": "http://h/a.png"}}
                ]
            },
        ),
    ],
)
def test_build_value(ptype: str, value: str, expected: dict) -> None:
    built = build_value(ptype, value)
    if ptype == "title":
        built["title"][0].pop("annotations")
    assert built == expected


@pytest.mark.parametrize(
    ("ptype", "value"),
    [
        ("number", "abc"),
        ("checkbox", "maybe"),
        ("formula", "x"),
        ("created_time", "x"),
        ("mystery", "x"),
    ],
)
def test_build_value_rejects(ptype: str, value: str) -> None:
    with pytest.raises(ValueError):
        build_value(ptype, value)


def test_build_properties_uses_schema_and_is_case_insensitive() -> None:
    schema = data_source()["properties"]
    built = build_properties(schema, ["status=Done", "Priority=High"])
    assert set(built) == {"Status", "Priority"}
    assert built["Status"] == {"status": {"name": "Done"}}


def test_build_properties_errors_name_the_property() -> None:
    schema = data_source()["properties"]
    with pytest.raises(ValueError, match="Progress"):
        build_properties(schema, ["Progress=1"])
    with pytest.raises(ValueError, match="unknown property 'Nope'"):
        build_properties(schema, ["Nope=1"])


def test_schema_summary() -> None:
    rows = {r["name"]: r for r in schema_summary(data_source()["properties"])}
    assert rows["Status"]["options"] == ["Not started", "In progress"]
    assert rows["Progress"]["writable"] is False
    assert rows["Project name"]["type"] == "title"


def test_build_schema_shapes() -> None:
    schema = build_schema(
        [
            "Name=title",
            "Kind=select:agent, human",
            "Active=checkbox",
            "Rel=relation:ds-1",
            "N=number:percent",
        ]
    )
    assert schema["Name"] == {"title": {}}
    assert schema["Kind"] == {"select": {"options": [{"name": "agent"}, {"name": "human"}]}}
    assert schema["Active"] == {"checkbox": {}}
    assert schema["Rel"] == {"relation": {"data_source_id": "ds-1", "single_property": {}}}
    assert schema["N"] == {"number": {"format": "percent"}}


def test_build_schema_adds_a_title_when_missing_and_rejects_bad_specs() -> None:
    assert list(build_schema(["Kind=select"])) == ["Name", "Kind"]
    assert build_schema([]) == {"Name": {"title": {}}}
    with pytest.raises(ValueError, match="unsupported property type"):
        build_schema(["X=formula"])
    with pytest.raises(ValueError, match="only one title"):
        build_schema(["A=title", "B=title"])
    with pytest.raises(ValueError, match="relation needs a target"):
        build_schema(["R=relation"])
    with pytest.raises(ValueError, match="duplicate"):
        build_schema(["A=url", "A=email"])
