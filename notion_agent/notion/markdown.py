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
from collections.abc import Callable
from typing import Any

RICH_TEXT_LIMIT = 2000
BLOCKS_PER_REQUEST = 100

_HEADING_TYPES = {"heading_1": 1, "heading_2": 2, "heading_3": 3}
_LIST_TYPES = ("bulleted_list_item", "numbered_list_item", "to_do")
_DASH_LISTS = {"bulleted_list_item", "to_do"}

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
    return [
        {
            "type": "text",
            "text": {"content": chunk, "link": {"url": link} if link else None},
            "annotations": _annotations(
                bold=bold, italic=italic, strikethrough=strikethrough, code=code
            ),
        }
        for chunk in text_chunks(text)
    ]


def plain_text(spans: list[dict[str, Any]] | None) -> str:
    return "".join(_span_text(s) for s in spans or [])


def _span_text(span: dict[str, Any]) -> str:
    if "plain_text" in span:
        return str(span["plain_text"])
    if span.get("type") == "text":
        return str(span.get("text", {}).get("content", ""))
    return ""


def _wrap_marks(text: str, ann: dict[str, Any]) -> str:
    """Apply inline marks in the canonical order (code innermost, strike outermost)."""
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
    return text


def _span_href(span: dict[str, Any]) -> str | None:
    """A link target for plain text spans (mentions keep their own href untouched)."""
    if span.get("type") not in (None, "text"):
        return None
    link = (span.get("text") or {}).get("link") or {}
    return link.get("url") or span.get("href")


def rich_text_to_markdown(spans: list[dict[str, Any]] | None) -> str:
    out = []
    for span in spans or []:
        text = _span_text(span)
        if not text:
            continue
        text = _wrap_marks(text, span.get("annotations", {}))
        href = _span_href(span)
        out.append(f"[{text}]({href})" if href else text)
    return "".join(out)


_INLINE_MARKERS = ("***", "**", "*", "~~", "`")
_MARKER_FLAGS: dict[str, dict[str, bool]] = {
    "***": {"bold": True, "italic": True},
    "**": {"bold": True},
    "*": {"italic": True},
    "~~": {"strikethrough": True},
}


def markdown_to_rich_text(text: str) -> list[dict[str, Any]]:
    """Parse inline Markdown (bold/italic/strike/code/link) into rich text."""
    return _parse_inline(text, {})


def _match_link(text: str, i: int) -> tuple[str, str, int] | None:
    """``[label](url)`` at ``i`` → (label, url, end index), else ``None``."""
    if text[i] != "[":
        return None
    close = text.find("](", i + 1)
    if close == -1:
        return None
    end = text.find(")", close + 2)
    if end == -1:
        return None
    return text[i + 1 : close], text[close + 2 : end], end + 1


def _match_marker(text: str, i: int) -> tuple[str, str, int] | None:
    """An inline mark opening at ``i`` → (marker, inner text, end index), else ``None``."""
    for marker in _INLINE_MARKERS:
        if not text.startswith(marker, i):
            continue
        close = text.find(marker, i + len(marker))
        if close == -1 or close == i + len(marker):
            continue
        inner = text[i + len(marker) : close]
        # Emphasis needs flanking non-space (`2 * 3 * 4` is arithmetic, not
        # italics); code spans are taken verbatim.
        if marker != "`" and (inner[0].isspace() or inner[-1].isspace()):
            continue
        return marker, inner, close + len(marker)
    return None


def _parse_inline(text: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    buf = ""
    i = 0
    while i < len(text):
        link = _match_link(text, i)
        if link:
            label, url, i = link
            spans.extend(rich_text(buf, **state) if buf else [])
            buf = ""
            spans.extend(_parse_inline(label, {**state, "link": url}))
            continue
        mark = _match_marker(text, i)
        if mark:
            marker, inner, i = mark
            spans.extend(rich_text(buf, **state) if buf else [])
            buf = ""
            if marker == "`":
                spans.extend(rich_text(inner, **{**state, "code": True}))
            else:
                spans.extend(_parse_inline(inner, {**state, **_MARKER_FLAGS[marker]}))
            continue
        buf += text[i]
        i += 1
    if buf:
        spans.extend(rich_text(buf, **state))
    return spans


# --------------------------------------------------------------------------
# blocks → markdown
# --------------------------------------------------------------------------


def block_text(block: dict[str, Any]) -> str:
    """Plain text of a block's own rich text (no children)."""
    payload = block.get(block.get("type", ""), {}) or {}
    return plain_text(payload.get("rich_text"))


def _same_list_run(prev: str | None, current: str) -> bool:
    """Adjacent list items render without a blank line when Markdown treats them as one list."""
    if prev is None:
        return False
    if current == "numbered_list_item":
        return prev == "numbered_list_item"
    return current in _DASH_LISTS and prev in _DASH_LISTS


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
        if lines and not _same_list_run(prev_type, btype):
            lines.append("")
        lines.append(chunk)
        prev_type = btype
    return "\n".join(lines).rstrip("\n")


class _Ctx:
    """What a block renderer needs: the block, its indent, its list number."""

    def __init__(self, block: dict[str, Any], indent: int, number: int) -> None:
        self.block = block
        self.btype = block.get("type", "")
        self.payload: dict[str, Any] = block.get(self.btype, {}) or {}
        self.indent = indent
        self.pad = "  " * indent
        self.number = number
        self.text = rich_text_to_markdown(self.payload.get("rich_text"))
        # Fetched trees carry children on the block; outbound payloads (what
        # markdown_to_blocks builds) carry them inside the typed payload.
        self.children: list[dict[str, Any]] = (
            block.get("children") or self.payload.get("children") or []
        )

    def with_children(self, head: str, *, nested: bool = True, sep: str = "\n") -> str:
        if not self.children:
            return head
        child_indent = self.indent + 1 if nested else self.indent
        return head + sep + blocks_to_markdown(self.children, indent=child_indent)

    def children_only(self) -> str | None:
        return blocks_to_markdown(self.children, indent=self.indent) if self.children else None


def _file_url(payload: dict[str, Any]) -> str:
    kind = payload.get("type")
    if kind and isinstance(payload.get(kind), dict):
        return str(payload[kind].get("url", ""))
    return ""


def _r_heading(c: _Ctx) -> str:
    head = f"{c.pad}{'#' * _HEADING_TYPES[c.btype]} {c.text}"
    return c.with_children(head, nested=False, sep="\n\n")


def _r_paragraph(c: _Ctx) -> str:
    body = c.text.replace("\n", "\n" + c.pad) if c.pad else c.text
    return c.with_children(f"{c.pad}{body}", nested=False, sep="\n\n")


def _r_quote(c: _Ctx) -> str:
    quoted = "\n".join(f"{c.pad}> {line}" for line in c.text.split("\n"))
    return c.with_children(quoted, nested=False, sep="\n\n")


def _r_callout(c: _Ctx) -> str:
    emoji = (c.payload.get("icon") or {}).get("emoji") or "💡"
    return c.with_children(f"{c.pad}> {emoji} {c.text}", nested=False, sep="\n\n")


def _r_code(c: _Ctx) -> str:
    lang = c.payload.get("language") or ""
    raw = plain_text(c.payload.get("rich_text"))
    body = "\n".join(c.pad + line for line in raw.split("\n"))
    return f"{c.pad}```{lang}\n{body}\n{c.pad}```"


def _r_todo(c: _Ctx) -> str:
    mark = "x" if c.payload.get("checked") else " "
    return c.with_children(f"{c.pad}- [{mark}] {c.text}")


def _r_child_page(c: _Ctx) -> str:
    return f"{c.pad}📄 {c.payload.get('title', '')} (child page {c.block.get('id', '')})"


def _r_child_database(c: _Ctx) -> str:
    return f"{c.pad}🗃 {c.payload.get('title', '')} (child database {c.block.get('id', '')})"


def _r_media(c: _Ctx) -> str:
    caption = rich_text_to_markdown(c.payload.get("caption")) or c.btype
    return f"{c.pad}[{caption}]({_file_url(c.payload)})"


def _r_link_block(c: _Ctx) -> str:
    url = c.payload.get("url", "")
    caption = rich_text_to_markdown(c.payload.get("caption")) or url
    return f"{c.pad}[{caption}]({url})"


def _r_table(c: _Ctx) -> str:
    rows = [_render_block(child, indent=c.indent, number=0) or "" for child in c.children]
    return "\n".join(rows)


def _r_table_row(c: _Ctx) -> str:
    cells = [rich_text_to_markdown(cell) for cell in c.payload.get("cells", [])]
    return f"{c.pad}| " + " | ".join(cells) + " |"


_RENDERERS: dict[str, Callable[[_Ctx], str | None]] = {
    "heading_1": _r_heading,
    "heading_2": _r_heading,
    "heading_3": _r_heading,
    "paragraph": _r_paragraph,
    "bulleted_list_item": lambda c: c.with_children(f"{c.pad}- {c.text}"),
    "numbered_list_item": lambda c: c.with_children(f"{c.pad}{c.number}. {c.text}"),
    "to_do": _r_todo,
    "quote": _r_quote,
    "callout": _r_callout,
    "toggle": lambda c: c.with_children(f"{c.pad}- ▸ {c.text}"),
    "code": _r_code,
    "divider": lambda c: f"{c.pad}---",
    "child_page": _r_child_page,
    "child_database": _r_child_database,
    "image": _r_media,
    "file": _r_media,
    "pdf": _r_media,
    "video": _r_media,
    "audio": _r_media,
    "bookmark": _r_link_block,
    "embed": _r_link_block,
    "link_preview": _r_link_block,
    "equation": lambda c: f"{c.pad}$$ {c.payload.get('expression', '')} $$",
    "table": _r_table,
    "table_row": _r_table_row,
    "column_list": _Ctx.children_only,
    "column": _Ctx.children_only,
    "synced_block": _Ctx.children_only,
    "table_of_contents": lambda c: None,
    "breadcrumb": lambda c: None,
}


def _render_block(block: dict[str, Any], *, indent: int, number: int) -> str | None:
    c = _Ctx(block, indent, number)
    renderer = _RENDERERS.get(c.btype)
    if renderer is not None:
        return renderer(c)
    if c.btype == "unsupported" or not c.btype:
        return f"{c.pad}[unsupported block]"
    return c.with_children(f"{c.pad}[{c.btype}: {c.text or c.btype}]")


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


class _Parser:
    """Line-oriented Markdown → blocks state machine (see :func:`markdown_to_blocks`)."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.i = 0
        self.blocks: list[dict[str, Any]] = []
        # Stack of (indent, block) for nesting list items under their parent.
        self.list_stack: list[tuple[int, dict[str, Any]]] = []
        self.para: list[str] = []
        self.quote: list[str] = []

    # -- buffers ----------------------------------------------------------

    def flush_para(self) -> None:
        if self.para:
            self.blocks.append(_block("paragraph", markdown_to_rich_text("\n".join(self.para))))
            self.para.clear()

    def flush_quote(self) -> None:
        if self.quote:
            self.blocks.append(_block("quote", markdown_to_rich_text("\n".join(self.quote))))
            self.quote.clear()

    def flush_all(self) -> None:
        self.flush_para()
        self.flush_quote()

    def break_lists(self) -> None:
        self.flush_all()
        self.list_stack.clear()

    def place_list_item(self, indent: int, item: dict[str, Any]) -> None:
        self.flush_all()
        while self.list_stack and self.list_stack[-1][0] >= indent:
            self.list_stack.pop()
        if self.list_stack:
            parent = self.list_stack[-1][1]
            parent[parent["type"]].setdefault("children", []).append(item)
        else:
            self.blocks.append(item)
        self.list_stack.append((indent, item))

    # -- line handlers: each returns True when it consumed the line -------

    def fence(self, line: str, stripped: str) -> bool:
        fence = _FENCE_RE.match(stripped)
        if not fence:
            return False
        self.break_lists()
        lang = fence.group(1) or "plain text"
        body: list[str] = []
        self.i += 1
        while self.i < len(self.lines) and not _FENCE_RE.match(self.lines[self.i].strip()):
            body.append(self.lines[self.i])
            self.i += 1
        self.i += 1  # closing fence
        self.blocks.append(_block("code", rich_text("\n".join(body)), language=lang))
        return True

    def blank(self, line: str, stripped: str) -> bool:
        if stripped:
            return False
        self.flush_all()
        self.i += 1
        return True

    def divider(self, line: str, stripped: str) -> bool:
        if not _DIVIDER_RE.match(stripped):
            return False
        self.break_lists()
        self.blocks.append({"object": "block", "type": "divider", "divider": {}})
        self.i += 1
        return True

    def heading(self, line: str, stripped: str) -> bool:
        heading = _HEADING_RE.match(stripped)
        if not heading:
            return False
        self.break_lists()
        level = min(len(heading.group(1)), 3)
        spans = markdown_to_rich_text(heading.group(2) or "")
        self.blocks.append(_block(f"heading_{level}", spans))
        self.i += 1
        return True

    def quote_line(self, line: str, stripped: str) -> bool:
        quoted = _QUOTE_RE.match(stripped)
        if not quoted:
            return False
        self.flush_para()
        self.list_stack.clear()
        self.quote.append(quoted.group(1))
        self.i += 1
        return True

    def todo(self, line: str, stripped: str) -> bool:
        todo = _TODO_RE.match(line)
        if not todo:
            return False
        item = _block(
            "to_do",
            markdown_to_rich_text(todo.group(3) or ""),
            checked=todo.group(2).lower() == "x",
        )
        self.place_list_item(len(todo.group(1).expandtabs(2)), item)
        self.i += 1
        return True

    def bullet(self, line: str, stripped: str) -> bool:
        bullet = _BULLET_RE.match(line)
        if not bullet:
            return False
        item = _block("bulleted_list_item", markdown_to_rich_text(bullet.group(2) or ""))
        self.place_list_item(len(bullet.group(1).expandtabs(2)), item)
        self.i += 1
        return True

    def numbered(self, line: str, stripped: str) -> bool:
        numbered = _NUMBER_RE.match(line)
        if not numbered:
            return False
        item = _block("numbered_list_item", markdown_to_rich_text(numbered.group(2) or ""))
        self.place_list_item(len(numbered.group(1).expandtabs(2)), item)
        self.i += 1
        return True

    def text(self, line: str, stripped: str) -> bool:
        # Plain text: continues a paragraph.
        self.flush_quote()
        self.list_stack.clear()
        self.para.append(stripped)
        self.i += 1
        return True

    def run(self) -> list[dict[str, Any]]:
        # Order matters: to-dos before bullets (a to-do is a bullet with a box).
        handlers = (
            self.fence,
            self.blank,
            self.divider,
            self.heading,
            self.quote_line,
            self.todo,
            self.bullet,
            self.numbered,
            self.text,
        )
        while self.i < len(self.lines):
            line = self.lines[self.i]
            stripped = line.strip()
            for handler in handlers:
                if handler(line, stripped):
                    break
        self.flush_all()
        return self.blocks


def markdown_to_blocks(text: str) -> list[dict[str, Any]]:
    """Parse Markdown into Notion block payloads (see module docstring)."""
    return _Parser(text.replace("\r\n", "\n").split("\n")).run()


def chunk_blocks(
    blocks: list[dict[str, Any]], size: int = BLOCKS_PER_REQUEST
) -> list[list[dict[str, Any]]]:
    """Split a block list into API-sized append batches."""
    return [blocks[i : i + size] for i in range(0, len(blocks), size)] or [[]]
