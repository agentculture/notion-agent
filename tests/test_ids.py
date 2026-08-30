"""Id / URL normalisation."""

from __future__ import annotations

import pytest

from notion_agent.notion.ids import normalize_id, short_id

DASHED = "3cb523dc-87bf-8062-9682-f5568590e1bd"
HEX = "3cb523dc87bf80629682f5568590e1bd"


@pytest.mark.parametrize(
    "value",
    [
        DASHED,
        HEX,
        DASHED.upper(),
        f"  {HEX} ",
        f"https://www.notion.so/Cross-platform-Plan-{HEX}",
        f"https://www.notion.so/workspace/{HEX}?v=deadbeefdeadbeefdeadbeefdeadbeef",
        f"https://app.notion.com/p/Cross-platform-{HEX}",
        f"notion.so/{HEX}",
    ],
)
def test_normalize_id_accepts_all_forms(value: str) -> None:
    assert normalize_id(value) == DASHED


def test_p_query_param_wins_over_path_id() -> None:
    view = "v=cafecafecafecafecafecafecafecafe"
    url = f"https://www.notion.so/ws/deadbeefdeadbeefdeadbeefdeadbeef?{view}&p={HEX}"
    assert normalize_id(url) == DASHED


@pytest.mark.parametrize(
    "value", ["", "   ", "not-an-id", "https://www.notion.so/Just-A-Title", "12345"]
)
def test_normalize_id_rejects_garbage(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_id(value)


def test_short_id() -> None:
    assert short_id(DASHED) == HEX
