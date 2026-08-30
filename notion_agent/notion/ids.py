"""Notion id normalisation — accept whatever an agent is likely to paste.

Notion ids appear as dashed UUIDs (``3cb523dc-87bf-8062-9682-f5568590e1bd``),
as 32 hex characters (``3cb523dc87bf80629682f5568590e1bd``), or embedded in a
URL (``https://www.notion.so/Title-3cb523dc87bf80629682f5568590e1bd?v=...``,
``https://app.notion.com/p/3cb5...``). :func:`normalize_id` accepts all three and
returns the dashed form the API expects. Pure; no I/O.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

_UUID_RE = re.compile(
    r"([0-9a-fA-F]{8})-?([0-9a-fA-F]{4})-?([0-9a-fA-F]{4})-?([0-9a-fA-F]{4})-?([0-9a-fA-F]{12})"
)


def dashed(match: re.Match[str]) -> str:
    return "-".join(match.groups()).lower()


def normalize_id(value: str) -> str:
    """Return the dashed UUID for a raw id or a Notion URL.

    Raises :class:`ValueError` when no id can be found. In a URL the ``p=``
    query parameter (a page opened as a modal over a database view) wins over
    the id in the path; the ``v=`` view id is never picked.
    """
    text = (value or "").strip()
    if not text:
        raise ValueError("empty id")
    if "://" in text or text.startswith(("notion.so/", "www.notion.so/", "app.notion.com/")):
        return _from_url(text if "://" in text else "https://" + text)
    match = _UUID_RE.fullmatch(text)
    if match is None:
        raise ValueError(f"not a Notion id or URL: {value!r}")
    return dashed(match)


def _from_url(url: str) -> str:
    parts = urlsplit(url)
    params = parse_qs(parts.query)
    for candidate in params.get("p", []):
        match = _UUID_RE.fullmatch(candidate.strip())
        if match:
            return dashed(match)
    matches = list(_UUID_RE.finditer(parts.path))
    if not matches:
        raise ValueError(f"no Notion id found in URL: {url!r}")
    return dashed(matches[-1])


def short_id(value: str) -> str:
    """32-hex form (what Notion puts in URLs)."""
    return normalize_id(value).replace("-", "")
