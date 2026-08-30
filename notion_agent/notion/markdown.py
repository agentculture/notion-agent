"""Markdown ⇄ Notion blocks — the CLI's canonical text representation.

Blocks are a tree, not text. Every verb that reads or writes page content goes
through these two **pure** functions (no HTTP, no I/O):

* :func:`blocks_to_markdown` renders a block tree (children nested under a
  ``"children"`` key, as :meth:`NotionClient.block_tree` produces) to Markdown.
* :func:`markdown_to_blocks` parses Markdown into block payloads ready for
  ``PATCH /blocks/{id}/children`` or a page ``children`` array.

Supported round-trip subset (``md → blocks → md`` is the identity for canonical
input; see ``tests/test_markdown.py``):

- headings ``#`` / ``##`` / ``###`` (deeper headings clamp to ``###``)
- paragraphs (blank-line separated; single newlines stay inside a paragraph)
- bulleted (``- ``) and numbered (``1. ``) lists, nested by two-space indent
- to-dos ``- [ ]`` / ``- [x]``
- block quotes ``> ``
- fenced code blocks with an optional language
- ``---`` dividers
- inline **bold**, *italic*, ~~strikethrough~~, `code`, and [links](url)

Read-only renderings (rendered on the way out, never parsed back): callouts
(``> 💡``), toggles, child pages / databases, images / files / bookmarks /
embeds (as links), tables (as pipe rows), equations, and a labelled
placeholder for anything else — so an agent always sees *something* rather than
silently losing content.

Rich-text limits: Notion caps a single text object at 2,000 characters, so
long runs are chunked (:func:`text_chunks`).
"""

from __future__ import annotations

import re
from typing import Any

RICH_TEXT_LIMIT = 2000
BLOCKS_PER_REQUEST = 100

_HEADING_TYPES = {"heading_1": 1, "heading_2": 2, "heading_3": 3}
_LIST_TYPES = ("bulleted_list_item", "numbered_list_item", "to_do")
_TEXT_TYPES = (
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "quote",
    "callout",
    "toggle",
    "code",
)

# --------------------------------------------------------------------------
# rich text
# --------------------------------------------------------------------------


def _annotations(**overrides: bool) -> dict[str, Any]:
    base = {
        "bold": False,
        "italic": False,
        "strikethrough": False,
        "underline": False,
        "code": False,
        "color": "default",
    }
    base.update(overrides)
    return base


def text_chunks(text: str, limit: int = RICH_TEXT_LIMIT) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [""]


def rich_text(
    text: str,
    *,
    link: str | None = None,
    bold: bool = False,
    italic: bool = False,
    strikethrough: bool = False,
    code: bool = False,
) -> list[dict[str, Any]]:
    """Build rich-text objects for ``text`` (chunked to the API limit)."""
    spans = []
    for chunk in text_chunks(text):
        obj: dict[str, Any] = {
            "type": "text",
            "text": {"content": chunk, "link": {"url": link} if link else None},
            "annotations": _annotations(
                bold=bold, italic=italic, strikethrough=strikethrough, code=code
            ),
        }
        spans.append(obj)
    return spans


def plain_text(spans: list[dict[str, Any]] | None) -> str:
    return "".join(_span_text(s) for s in spans or [])


def _span_text(span: dict[str, Any]) -> str:
    if "plain_text" in span:
        return str(span["plain_text"])
    if span.get("type") == "text":
        return str(span.get("text", {}).get("content", ""))
    return ""


def rich_text_to_markdown(spans: list[dict[str, Any]] | None) -> str:
    out = []
    for span in spans or []:
        text = _span_text(span)
        if not text:
            continue
        ann = span.get("annotations", {})
        if ann.get("code"):
            text = f"`{text}`"
        if ann.get("bold") and ann.get("italic"):
            text = f"***{text}***"
        elif ann.get("bold"):
            text = f"**{text}**"
        elif ann.get("italic"):
            text = f"*{text}*"
        if ann.get("strikethrough"):
            text = f"~~{text}~~"
        href = span.get("href")
        if span.get("type") == "text":
            link = (span.get("text") or {}).get("link") or {}
            href = link.get("url") or href
        if href and span.get("type") in (None, "text"):
            text = f"[{text}]({href})"
        out.append(text)
    return "".join(out)


_INLINE_MARKERS = ("***", "**", "*", "~~", "`")


def markdown_to_rich_text(text: str) -> list[dict[str, Any]]:
    """Parse inline Markdown (bold/italic/strike/code/link) into rich text."""
    return _parse_inline(text, {})


def _parse_inline(text: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    buf = ""
    i = 0
    n = len(text)

    def flush() -> None:
        nonlocal buf
        if buf:
            spans.extend(rich_text(buf, **state))
            buf = ""

    while i < n:
        # links: [text](url)
        if text[i] == "[":
            close = text.find("](", i + 1)
            if close != -1:
                end = text.find(")", close + 2)
                if end != -1:
                    inner, url = text[i + 1 : close], text[close + 2 : end]
                    flush()
                    spans.extend(_parse_inline(inner, {**state, "link": url}))
                    i = end + 1
                    continue
        matched = False
        for marker in _INLINE_MARKERS:
            if text.startswith(marker, i):
                close = text.find(marker, i + len(marker))
                if close == -1 or close == i + len(marker):
                    continue
                inner = text[i + len(marker) : close]
                # Emphasis needs flanking non-space (`2 * 3 * 4` is arithmetic,
                # not italics); code spans are taken verbatim.
                if marker != "`" and (inner[0].isspace() or inner[-1].isspace()):
                    continue
                flush()
                if marker == "`":
                    spans.extend(rich_text(inner, **{**state, "code": True}))
                else:
                    flag = {
                        "***": {"bold": True, "italic": True},
                        "**": {"bold": True},
                        "*": {"italic": True},
                        "~~": {"strikethrough": True},
                    }[marker]
                    spans.extend(_parse_inline(inner, {**state, **flag}))
                i = close + len(marker)
                matched = True
                break
        if matched:
            continue
        buf += text[i]
        i += 1
    flush()
    return spans


# --------------------------------------------------------------------------
# blocks → markdown
# --------------------------------------------------------------------------


def block_text(block: dict[str, Any]) -> str:
    """Plain text of a block's own rich text (no children)."""
    payload = block.get(block.get("type", ""), {}) or {}
    return plain_text(payload.get("rich_text") or payload.get("title") and [] or [])


def blocks_to_markdown(blocks: list[dict[str, Any]], *, indent: int = 0) -> str:
    """Render a block tree to Markdown."""
    lines: list[str] = []
    number = 0
    prev_type: str | None = None
    for block in blocks:
        btype = block.get("type", "")
        number = number + 1 if btype == "numbered_list_item" else 0
        chunk = _render_block(block, indent=indent, number=number)
        if chunk is None:
            continue
        separator_free = _same_list_run(prev_type, btype)
        if lines and not separator_free:
            lines.append("")
        lines.append(chunk)
        prev_type = btype
    return "\n".join(lines).rstrip("\n")


_DASH_LISTS = {"bulleted_list_item", "to_do"}


def _same_list_run(prev: str | None, current: str) -> bool:
    """Adjacent list items render without a blank line when Markdown treats them as one list."""
    if prev is None:
        return False
    if current == "numbered_list_item":
        return prev == "numbered_list_item"
    return current in _DASH_LISTS and prev in _DASH_LISTS


def _render_block(block: dict[str, Any], *, indent: int, number: int) -> str | None:
    btype = block.get("type", "")
    payload = block.get(btype, {}) or {}
    pad = "  " * indent
    text = rich_text_to_markdown(payload.get("rich_text"))
    # Fetched trees carry children on the block; outbound payloads (what
    # markdown_to_blocks builds) carry them inside the typed payload.
    children = block.get("children") or payload.get("children") or []

    def with_children(head: str, child_indent: int = indent + 1, sep: str = "\n") -> str:
        if not children:
            return head
        return head + sep + blocks_to_markdown(children, indent=child_indent)

    if btype in _HEADING_TYPES:
        return with_children(f"{pad}{'#' * _HEADING_TYPES[btype]} {text}", indent, "\n\n")
    if btype == "paragraph":
        body = text.replace("\n", "\n" + pad) if pad else text
        return with_children(f"{pad}{body}", indent, "\n\n")
    if btype == "bulleted_list_item":
        return with_children(f"{pad}- {text}")
    if btype == "numbered_list_item":
        return with_children(f"{pad}{number}. {text}")
    if btype == "to_do":
        mark = "x" if payload.get("checked") else " "
        return with_children(f"{pad}- [{mark}] {text}")
    if btype == "quote":
        quoted = "\n".join(f"{pad}> {line}" for line in text.split("\n"))
        return with_children(quoted, indent, "\n\n")
    if btype == "callout":
        icon = payload.get("icon") or {}
        emoji = icon.get("emoji") or "💡"
        return with_children(f"{pad}> {emoji} {text}", indent, "\n\n")
    if btype == "toggle":
        return with_children(f"{pad}- ▸ {text}")
    if btype == "code":
        lang = payload.get("language") or ""
        raw = plain_text(payload.get("rich_text"))
        body = "\n".join(pad + line for line in raw.split("\n"))
        return f"{pad}```{lang}\n{body}\n{pad}```"
    if btype == "divider":
        return f"{pad}---"
    if btype == "child_page":
        return f"{pad}📄 {payload.get('title', '')} (child page {block.get('id', '')})"
    if btype == "child_database":
        return f"{pad}🗃 {payload.get('title', '')} (child database {block.get('id', '')})"
    if btype in ("image", "file", "pdf", "video", "audio"):
        url = _file_url(payload)
        caption = rich_text_to_markdown(payload.get("caption")) or btype
        return f"{pad}[{caption}]({url})"
    if btype in ("bookmark", "embed", "link_preview"):
        url = payload.get("url", "")
        caption = rich_text_to_markdown(payload.get("caption")) or url
        return f"{pad}[{caption}]({url})"
    if btype == "equation":
        return f"{pad}$$ {payload.get('expression', '')} $$"
    if btype == "table":
        rows = [_render_block(c, indent=indent, number=0) or "" for c in children]
        return "\n".join(rows)
    if btype == "table_row":
        cells = [rich_text_to_markdown(cell) for cell in payload.get("cells", [])]
        return f"{pad}| " + " | ".join(cells) + " |"
    if btype == "column_list":
        return blocks_to_markdown(children, indent=indent) if children else None
    if btype == "column":
        return blocks_to_markdown(children, indent=indent) if children else None
    if btype == "synced_block":
        return blocks_to_markdown(children, indent=indent) if children else None
    if btype in ("table_of_contents", "breadcrumb"):
        return None
    if btype == "unsupported" or not btype:
        return f"{pad}[unsupported block]"
    label = text or btype
    return with_children(f"{pad}[{btype}: {label}]")


def _file_url(payload: dict[str, Any]) -> str:
    kind = payload.get("type")
    if kind and isinstance(payload.get(kind), dict):
        return str(payload[kind].get("url", ""))
    return ""


# --------------------------------------------------------------------------
# markdown → blocks
# --------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(\S.*)?$")
_BULLET_RE = re.compile(r"^([ \t]*)[-*+][ \t]+(\S.*)?$")
_TODO_RE = re.compile(r"^([ \t]*)[-*+][ \t]+\[([ xX])\](?:[ \t]+(\S.*)?)?$")
_NUMBER_RE = re.compile(r"^([ \t]*)\d+[.)][ \t]+(\S.*)?$")
_QUOTE_RE = re.compile(r"^>[ \t]?(.*)$")
_FENCE_RE = re.compile(r"^```[ \t]*([^\s`]*)$")
_DIVIDER_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")


def _block(btype: str, spans: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"rich_text": spans}
    payload.update(extra)
    return {"object": "block", "type": btype, btype: payload}


def markdown_to_blocks(text: str) -> list[dict[str, Any]]:
    """Parse Markdown into Notion block payloads (see module docstring)."""
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[dict[str, Any]] = []
    # Stack of (indent, block) for nesting list items under their parent.
    list_stack: list[tuple[int, dict[str, Any]]] = []
    para: list[str] = []
    quote: list[str] = []
    i = 0

    def flush_para() -> None:
        if para:
            blocks.append(_block("paragraph", markdown_to_rich_text("\n".join(para))))
            para.clear()

    def flush_quote() -> None:
        if quote:
            blocks.append(_block("quote", markdown_to_rich_text("\n".join(quote))))
            quote.clear()

    def flush_all() -> None:
        flush_para()
        flush_quote()

    def place_list_item(indent: int, item: dict[str, Any]) -> None:
        while list_stack and list_stack[-1][0] >= indent:
            list_stack.pop()
        if list_stack:
            parent = list_stack[-1][1]
            parent[parent["type"]].setdefault("children", []).append(item)
        else:
            blocks.append(item)
        list_stack.append((indent, item))

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        fence = _FENCE_RE.match(stripped)
        if fence:
            flush_all()
            list_stack.clear()
            lang = fence.group(1) or "plain text"
            body: list[str] = []
            i += 1
            while i < len(lines) and not _FENCE_RE.match(lines[i].strip()):
                body.append(lines[i])
                i += 1
            i += 1  # closing fence
            blocks.append(_block("code", rich_text("\n".join(body)), language=lang))
            continue

        if not stripped:
            flush_all()
            i += 1
            continue

        if _DIVIDER_RE.match(stripped):
            flush_all()
            list_stack.clear()
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            flush_all()
            list_stack.clear()
            level = min(len(heading.group(1)), 3)
            blocks.append(_block(f"heading_{level}", markdown_to_rich_text(heading.group(2) or "")))
            i += 1
            continue

        quoted = _QUOTE_RE.match(stripped)
        if quoted:
            flush_para()
            list_stack.clear()
            quote.append(quoted.group(1))
            i += 1
            continue

        todo = _TODO_RE.match(line)
        if todo:
            flush_all()
            indent = len(todo.group(1).expandtabs(2))
            item = _block(
                "to_do",
                markdown_to_rich_text(todo.group(3) or ""),
                checked=todo.group(2).lower() == "x",
            )
            place_list_item(indent, item)
            i += 1
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            flush_all()
            indent = len(bullet.group(1).expandtabs(2))
            place_list_item(
                indent, _block("bulleted_list_item", markdown_to_rich_text(bullet.group(2) or ""))
            )
            i += 1
            continue

        numbered = _NUMBER_RE.match(line)
        if numbered:
            flush_all()
            indent = len(numbered.group(1).expandtabs(2))
            place_list_item(
                indent, _block("numbered_list_item", markdown_to_rich_text(numbered.group(2) or ""))
            )
            i += 1
            continue

        # Plain text: continues a paragraph (or a list item's paragraph run).
        flush_quote()
        list_stack.clear()
        para.append(stripped)
        i += 1

    flush_all()
    return blocks


def chunk_blocks(
    blocks: list[dict[str, Any]], size: int = BLOCKS_PER_REQUEST
) -> list[list[dict[str, Any]]]:
    """Split a block list into API-sized append batches."""
    return [blocks[i : i + size] for i in range(0, len(blocks), size)] or [[]]
