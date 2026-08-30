"""The Notion client layer — shared by every noun in ``cli/_commands``.

Zero third-party dependencies (``urllib`` only). See :mod:`.client` for auth,
versioning, rate limiting and pagination; :mod:`.markdown` for the
Markdown ⇄ blocks conversion; :mod:`.props` for property values; :mod:`.ids`
for id/URL normalisation.
"""

from __future__ import annotations

from notion_agent.notion.client import (
    DEFAULT_VERSION,
    TOKEN_ENV_VARS,
    NotionClient,
    NotionError,
    Request,
    Response,
    token_from_env,
)
from notion_agent.notion.ids import normalize_id
from notion_agent.notion.markdown import blocks_to_markdown, markdown_to_blocks

__all__ = [
    "DEFAULT_VERSION",
    "TOKEN_ENV_VARS",
    "NotionClient",
    "NotionError",
    "Request",
    "Response",
    "blocks_to_markdown",
    "markdown_to_blocks",
    "normalize_id",
    "token_from_env",
]
