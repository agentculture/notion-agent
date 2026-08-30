"""Shared plumbing for the Notion noun groups (search, page, db, block, comment).

Three things every Notion verb needs, in one place so no verb re-derives them:

* :func:`get_client` — the :class:`NotionClient` for this process, built from
  the environment (``NOTION_API_KEY`` → ``NOTION_TOKEN``). A missing token is
  an **environment** error (exit 2) with a hint naming the variable. Tests
  monkeypatch :func:`build_client` to inject a fake transport.
* :func:`to_cli_error` — the single :class:`NotionError` → :class:`CliError`
  mapping. It turns Notion's ``object_not_found`` into the first-class *"not
  shared with the integration"* message (issue #1, parked unknown 3), maps
  ``unauthorized`` to exit 2, and always carries Notion's ``request_id`` in the
  message so a support trail exists. The bearer token never appears in any
  message.
* :func:`emit_plan` / :func:`Plan` — the **dry-run contract**. Every write verb
  builds a :class:`Plan` (a list of ``method``/``path``/``body`` steps) and
  either prints it (default) or executes it (``--apply``). Plans print method,
  path and body only — never headers.

Plus small helpers: :func:`notion_command` (wraps a handler so ``NotionError``
and ``ValueError`` become ``CliError``), :func:`add_json_flag`,
:func:`add_apply_flag`, :func:`read_body`, :func:`parse_id`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from notion_agent.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from notion_agent.cli._output import emit_diagnostic, emit_result
from notion_agent.notion.client import TOKEN_ENV_VARS, NotionClient, NotionError, token_from_env
from notion_agent.notion.ids import normalize_id

_SHARE_HINT = (
    "open the page or database in Notion → '...' menu → Connections → add this integration, "
    "then retry; or check the id"
)


# --------------------------------------------------------------------------
# client
# --------------------------------------------------------------------------


def build_client() -> NotionClient:
    """Construct the live client. Tests monkeypatch this to inject a fake transport."""
    found = token_from_env()
    if found is None:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"no Notion token found in the environment ({' or '.join(TOKEN_ENV_VARS)})",
            remediation=(
                "export NOTION_API_KEY=<internal integration or personal access token> "
                "(create one at https://www.notion.so/profile/integrations)"
            ),
        )
    token, source = found
    client = NotionClient(token)
    client.token_source = source  # type: ignore[attr-defined] - reported by whoami
    return client


def get_client(_args: argparse.Namespace | None = None) -> NotionClient:
    return build_client()


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------


def _with_request_id(message: str, err: NotionError) -> str:
    return f"{message} (request_id {err.request_id})" if err.request_id else message


def to_cli_error(err: NotionError) -> CliError:
    """Map a :class:`NotionError` to the CLI's structured error contract."""
    if err.code == "network_error":
        return CliError(
            code=EXIT_ENV_ERROR,
            message=err.message,
            remediation="check network access to api.notion.com and retry",
        )
    if err.status == 401 or err.code == "unauthorized":
        return CliError(
            code=EXIT_ENV_ERROR,
            message=_with_request_id("Notion rejected the token: " + err.message, err),
            remediation=(
                "check NOTION_API_KEY (or NOTION_TOKEN) — it may be revoked or from another "
                "workspace; 'notion whoami' probes it"
            ),
        )
    if err.code == "object_not_found":
        integration = _integration_name(err.message)
        who = f"the integration '{integration}'" if integration else "the integration"
        return CliError(
            code=EXIT_USER_ERROR,
            message=_with_request_id(
                f"object not found or not shared with {who}: {err.message}", err
            ),
            remediation=_SHARE_HINT,
        )
    if err.code == "restricted_resource" or err.status == 403:
        return CliError(
            code=EXIT_USER_ERROR,
            message=_with_request_id("Notion refused the request: " + err.message, err),
            remediation="this token's type or capabilities do not allow the operation",
        )
    if err.status == 429 or err.code == "rate_limited":
        return CliError(
            code=EXIT_ENV_ERROR,
            message=_with_request_id("Notion rate limit still exceeded after retries", err),
            remediation="wait a few seconds and retry; the client already backs off on 429",
        )
    if err.status >= 500:
        return CliError(
            code=EXIT_ENV_ERROR,
            message=_with_request_id(f"Notion server error {err.status}: {err.message}", err),
            remediation="retry; a write that failed this way was not replayed automatically",
        )
    return CliError(
        code=EXIT_USER_ERROR,
        message=_with_request_id(f"Notion rejected the request ({err.code}): {err.message}", err),
        remediation="run 'notion-agent explain <noun> <verb>' for the expected inputs",
    )


def _integration_name(message: str) -> str | None:
    # Notion's own 404 text ends with: ...shared with your integration "Spark".
    marker = 'integration "'
    start = message.find(marker)
    if start == -1:
        return None
    end = message.find('"', start + len(marker))
    return message[start + len(marker) : end] if end != -1 else None


def notion_command(handler: Callable[[argparse.Namespace], int | None]):
    """Wrap a handler so :class:`NotionError` / :class:`ValueError` become :class:`CliError`."""

    def wrapped(args: argparse.Namespace) -> int | None:
        try:
            return handler(args)
        except NotionError as err:
            raise to_cli_error(err) from err
        except ValueError as err:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=str(err),
                remediation="run 'notion-agent explain <noun> <verb>' for the expected inputs",
            ) from err

    wrapped.__name__ = getattr(handler, "__name__", "handler")
    wrapped.__doc__ = handler.__doc__
    return wrapped


# --------------------------------------------------------------------------
# the dry-run contract
# --------------------------------------------------------------------------


@dataclass
class Step:
    method: str
    path: str
    body: dict[str, Any] | None = None
    describe: str = ""


@dataclass
class Plan:
    """A write verb's intent: the request(s) it would send, in order."""

    summary: str
    steps: list[Step] = field(default_factory=list)

    def add(
        self, method: str, path: str, body: dict[str, Any] | None = None, describe: str = ""
    ) -> Step:
        step = Step(method.upper(), path, body, describe)
        self.steps.append(step)
        return step

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": True,
            "summary": self.summary,
            "requests": [
                {"method": s.method, "path": s.path, "body": s.body, "describe": s.describe}
                for s in self.steps
            ],
        }

    def render_text(self) -> str:
        lines = [f"dry-run: {self.summary}"]
        for step in self.steps:
            lines.append(
                f"  {step.method} {step.path}" + (f"  # {step.describe}" if step.describe else "")
            )
            if step.body is not None:
                lines.append("  " + json.dumps(step.body, ensure_ascii=False))
        lines.append("re-run with --apply to perform it")
        return "\n".join(lines)


def emit_plan(plan: Plan, *, json_mode: bool) -> None:
    """Print a plan (the dry-run result) to stdout. Headers are never included."""
    if json_mode:
        emit_result(plan.to_dict(), json_mode=True)
    else:
        emit_result(plan.render_text(), json_mode=False)


def applying(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "apply", False))


def run_plan(client: NotionClient, plan: Plan) -> list[dict[str, Any]]:
    """Execute every step in order; return each response body."""
    results = []
    for step in plan.steps:
        results.append(client.request(step.method, step.path, body=step.body))
    return results


# --------------------------------------------------------------------------
# argparse helpers
# --------------------------------------------------------------------------


def add_json_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")


def add_apply_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--apply",
        action="store_true",
        help="Perform the write. Without it the planned request(s) are printed and nothing "
        "is sent (dry run).",
    )


def add_body_flags(p: argparse.ArgumentParser, *, required: bool = False) -> None:
    group = p.add_mutually_exclusive_group(required=required)
    group.add_argument("--body", help="Markdown content (inline).")
    group.add_argument(
        "--body-file",
        help="Read Markdown content from a file ('-' for stdin).",
    )


def read_body(args: argparse.Namespace) -> str | None:
    """Return the Markdown body from ``--body`` / ``--body-file``, or ``None``."""
    body = getattr(args, "body", None)
    if body is not None:
        return body
    path = getattr(args, "body_file", None)
    if path is None:
        return None
    if path == "-":
        return sys.stdin.read()
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as err:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"cannot read {path}: {err.strerror or err}",
            remediation="check the path and permissions",
        ) from err


def parse_id(value: str, what: str = "id") -> str:
    try:
        return normalize_id(value)
    except ValueError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"invalid {what}: {err}",
            remediation="pass a Notion id (dashed or 32-hex) or a notion.so / app.notion.com URL",
        ) from err


def json_mode(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False))


def note(message: str) -> None:
    """A stderr diagnostic (progress / summary) that never pollutes stdout."""
    emit_diagnostic(message)


def noun_help(p: argparse.ArgumentParser) -> Callable[[argparse.Namespace], int]:
    """Handler for a bare noun (``notion page``): print its help, exit 0."""

    def _show(_args: argparse.Namespace) -> int:
        p.print_help()
        return 0

    return _show


def resolve_data_source(client: NotionClient, any_id: str) -> dict[str, Any]:
    """Return the data source for ``any_id``, accepting a data source *or* database id.

    A database with exactly one data source resolves to it; several raise a
    :class:`CliError` listing the choices so the caller can pick.
    """
    try:
        return client.get_data_source(any_id)
    except NotionError as err:
        if err.code not in ("object_not_found", "validation_error") and err.status != 400:
            raise
    db = client.get_database(any_id)
    sources = db.get("data_sources") or []
    if len(sources) == 1:
        return client.get_data_source(sources[0]["id"])
    listing = ", ".join(f"{s.get('name', '?')} ({s['id']})" for s in sources) or "none"
    raise CliError(
        code=EXIT_USER_ERROR,
        message=f"database {any_id} has {len(sources)} data sources: {listing}",
        remediation="pass one data source id instead of the database id",
    )
