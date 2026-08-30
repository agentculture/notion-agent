"""``notion-agent whoami`` — the Notion auth probe.

Reports the agent's identity as declared in ``culture.yaml``: its nick
(``suffix``), the backend it runs on, and the served model (if any) — plus the
package version. It then probes Notion (``GET /users/me``) to confirm the
token actually works, naming the workspace, the integration, who owns it,
where the token came from, and the pinned API version.

A missing token is an environment error (exit 2) naming ``NOTION_API_KEY``;
a rejected token (401) surfaces Notion's ``request_id`` and never the secret.

When you clone this template, rename the package and update ``culture.yaml`` —
``whoami`` then reflects your new agent's identity with no code change.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from notion_agent import __version__
from notion_agent.cli._commands._common import get_client, notion_command
from notion_agent.cli._output import emit_result
from notion_agent.notion.client import NotionClient

_FALLBACK_NICK = "notion-agent"


def find_culture_yaml() -> Path | None:
    """Locate this agent's own ``culture.yaml`` by walking up from this module.

    The identity must be the agent's own, not whatever ``culture.yaml`` happens
    to sit in the caller's current working directory. In an editable / source
    install, walking up from ``__file__`` finds the repo root; in a wheel
    install no ``culture.yaml`` ships alongside the package and the caller falls
    back to the literal defaults.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "culture.yaml"
        if candidate.is_file():
            return candidate
    return None


def read_agent_fields() -> dict[str, str]:
    """Return ``suffix``/``backend``/``model`` from the first agent block.

    Parsed without a YAML dependency to keep the runtime deps empty. Reads
    top-level ``key: value`` lines within the first agent entry; anything
    fancier than the documented shape falls back to the defaults below.
    """
    fields = {"nick": _FALLBACK_NICK, "backend": "unknown", "model": "unknown"}
    cfg = find_culture_yaml()
    if cfg is None:
        return fields
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return fields
    seen_agent = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- suffix:", "suffix:")):
            if seen_agent:  # second agent block — stop at the first
                break
            seen_agent = True
            fields["nick"] = _scalar(stripped, "suffix")
        elif seen_agent and stripped.startswith("backend:"):
            fields["backend"] = _scalar(stripped, "backend")
        elif seen_agent and stripped.startswith("model:"):
            fields["model"] = _scalar(stripped, "model")
    return fields


def _scalar(line: str, key: str) -> str:
    """Extract the scalar after ``key:`` from a ``culture.yaml`` line."""
    _, _, value = line.partition(f"{key}:")
    return value.strip().strip("'\"") or "unknown"


def report() -> dict[str, object]:
    fields = read_agent_fields()
    return {
        "nick": fields["nick"],
        "version": __version__,
        "backend": fields["backend"],
        "model": fields["model"],
    }


def _probe(client: NotionClient) -> dict[str, str]:
    """The Notion half of ``whoami``: who this token is, and where it came from."""
    me = client.me()
    bot = me.get("bot", {})
    owner = bot.get("owner", {})
    if owner.get("type") == "user":
        owner_name = owner.get("user", {}).get("name", "unknown")
    else:
        owner_name = "workspace"
    return {
        "workspace": bot.get("workspace_name", "unknown"),
        "workspace_id": bot.get("workspace_id", "unknown"),
        "integration": me.get("name", "unknown"),
        "integration_id": me.get("id", "unknown"),
        "owner": owner_name,
        "token_source": getattr(client, "token_source", "env"),
        "api_version": client.version,
    }


def cmd_whoami(args: argparse.Namespace) -> None:
    identity = report()
    probe = _probe(get_client(args))
    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        payload: dict[str, Any] = dict(identity)
        payload["notion"] = probe
        emit_result(payload, json_mode=True)
        return
    text = (
        f"nick: {identity['nick']}\n"
        f"version: {identity['version']}\n"
        f"backend: {identity['backend']}\n"
        f"model: {identity['model']}\n"
        f"workspace: {probe['workspace']}\n"
        f"integration: {probe['integration']} ({probe['owner']})\n"
        f"token: {probe['token_source']}\n"
        f"api_version: {probe['api_version']}"
    )
    emit_result(text, json_mode=False)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "whoami",
        help="Report this agent's identity and probe the Notion token (GET /users/me).",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=notion_command(cmd_whoami))
