"""Entry point for ``python -m notion_agent``."""

from __future__ import annotations

import sys

from notion_agent.cli import main

if __name__ == "__main__":
    sys.exit(main())
