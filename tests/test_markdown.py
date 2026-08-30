"""Markdown ⇄ blocks: the round-trip guard and the lossy-but-visible renderings."""

from __future__ import annotations

import pytest

from notion_agent.notion.markdown import (
    RICH_TEXT_LIMIT,
    blocks_to_markdown,
    chunk_blocks,
    markdown_to_blocks,
    markdown_to_rich_text,
    plain_text,
    rich_text,
    rich_text_to_markdown,
)

CANONICAL = """\
# Background

Context, objectives, and scope of the document.
Second line of the same paragraph.

## Analysis

- first bullet with **bold** and *italic* and `code`
- second bullet with a [link](https://example.com) and ~~gone~~
  - nested child
    - grand child
- back to top level

1. step one
2. step two
  1. sub step

- [ ] open task
- [x] done task
- a bullet right after a to-do

> a quote
> that continues

```python
print("hi")
```

---

### Recommendations

***bold italic*** wrap-up."""


def test_round_trip_is_identity_on_canonical_markdown() -> None:
    blocks = markdown_to_blocks(CANONICAL)
    assert blocks_to_markdown(blocks) == CANONICAL


def test_round_trip_twice_is_stable() -> None:
    once = blocks_to_markdown(markdown_to_blocks(CANONICAL))
    assert blocks_to_markdown(markdown_to_blocks(once)) == once


def test_block_shapes() -> None:
    blocks = markdown_to_blocks(CANONICAL)
    types = [b["type"] for b in blocks]
    assert types == [
        "heading_1",
        "paragraph",
        "heading_2",
        "bulleted_list_item",
        "bulleted_list_item",
        "bulleted_list_item",
        "numbered_list_item",
        "numbered_list_item",
        "to_do",
        "to_do",
        "bulleted_list_item",
        "quote",
        "code",
        "divider",
        "heading_3",
        "paragraph",
    ]
    nested = blocks[4]["bulleted_list_item"]["children"]
    assert nested[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "nested child"
    assert nested[0]["bulleted_list_item"]["children"][0]["type"] == "bulleted_list_item"
    assert blocks[8]["to_do"]["checked"] is False
    assert blocks[9]["to_do"]["checked"] is True
    assert blocks[12]["code"]["language"] == "python"
    assert plain_text(blocks[12]["code"]["rich_text"]) == 'print("hi")'
    # Every block is a valid append payload: object + type + payload key.
    for b in blocks:
        assert b["object"] == "block"
        assert b["type"] in b


def test_inline_marks() -> None:
    spans = markdown_to_rich_text("plain **bold** *it* `c` ~~s~~ [l](http://x)")
    texts = [(s["text"]["content"], s["annotations"], s["text"]["link"]) for s in spans]
    assert texts[0] == ("plain ", spans[0]["annotations"], None)
    assert texts[1][0] == "bold"
    assert texts[1][1]["bold"]
    assert texts[3][0] == "it"
    assert texts[3][1]["italic"]
    assert texts[5][0] == "c"
    assert texts[5][1]["code"]
    assert texts[7][0] == "s"
    assert texts[7][1]["strikethrough"]
    assert texts[9] == ("l", spans[9]["annotations"], {"url": "http://x"})
    assert rich_text_to_markdown(spans) == "plain **bold** *it* `c` ~~s~~ [l](http://x)"


def test_unclosed_markers_are_literal() -> None:
    spans = markdown_to_rich_text("2 * 3 * 4 and a lone ** here")
    assert plain_text(spans) == "2 * 3 * 4 and a lone ** here"


def test_heading_deeper_than_three_clamps() -> None:
    assert markdown_to_blocks("##### deep")[0]["type"] == "heading_3"


def test_long_text_is_chunked() -> None:
    spans = rich_text("x" * (RICH_TEXT_LIMIT * 2 + 5))
    assert [len(s["text"]["content"]) for s in spans] == [RICH_TEXT_LIMIT, RICH_TEXT_LIMIT, 5]


def test_chunk_blocks() -> None:
    blocks = markdown_to_blocks("\n\n".join(f"p{i}" for i in range(250)))
    batches = chunk_blocks(blocks)
    assert [len(b) for b in batches] == [100, 100, 50]
    assert chunk_blocks([]) == [[]]


def _api_block(btype: str, **payload: object) -> dict:
    return {"object": "block", "id": "b", "type": btype, btype: payload, "has_children": False}


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        (_api_block("callout", rich_text=rich_text("note"), icon={"emoji": "⚠️"}), "> ⚠️ note"),
        (_api_block("toggle", rich_text=rich_text("more")), "- ▸ more"),
        (_api_block("child_page", title="Sub"), "📄 Sub (child page b)"),
        (_api_block("child_database", title="Tbl"), "🗃 Tbl (child database b)"),
        (
            _api_block("image", type="external", external={"url": "http://i"}, caption=[]),
            "[image](http://i)",
        ),
        (_api_block("bookmark", url="http://b", caption=[]), "[http://b](http://b)"),
        (_api_block("equation", expression="E=mc^2"), "$$ E=mc^2 $$"),
        (_api_block("unsupported"), "[unsupported block]"),
        (_api_block("video", type="file", file={"url": "http://v"}), "[video](http://v)"),
        (_api_block("breadcrumb"), ""),
        (_api_block("some_new_type", rich_text=rich_text("x")), "[some_new_type: x]"),
    ],
)
def test_read_only_renderings_never_vanish_silently(block: dict, expected: str) -> None:
    assert blocks_to_markdown([block]) == expected


def test_table_renders_pipe_rows() -> None:
    table = _api_block("table", table_width=2)
    table["children"] = [
        _api_block("table_row", cells=[rich_text("a"), rich_text("b")]),
        _api_block("table_row", cells=[rich_text("1"), rich_text("2")]),
    ]
    assert blocks_to_markdown([table]) == "| a | b |\n| 1 | 2 |"


def test_children_of_headings_and_paragraphs_render_after_them() -> None:
    para = _api_block("paragraph", rich_text=rich_text("intro"))
    para["children"] = [_api_block("paragraph", rich_text=rich_text("child"))]
    assert blocks_to_markdown([para]) == "intro\n\nchild"


def test_mention_and_equation_spans_use_plain_text() -> None:
    spans = [
        {"type": "mention", "plain_text": "@Ori", "annotations": {}, "href": None},
        {"type": "equation", "plain_text": "x", "annotations": {"bold": True}, "href": None},
    ]
    assert rich_text_to_markdown(spans) == "@Ori**x**"
