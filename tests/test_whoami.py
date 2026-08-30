"""Tests for ``notion-agent whoami`` — the Notion auth probe.

``whoami`` keeps the ``culture.yaml`` identity block and adds a live probe of
the token via ``GET /users/me``. These tests inject a fake transport by
monkeypatching ``_common.build_client``; the missing-token case uses the real
``build_client`` so the environment error (exit 2, naming ``NOTION_API_KEY``)
is exercised end to end.
"""

from __future__ import annotations

import json

import pytest

import notion_agent.cli._commands._common as common
from notion_agent.cli import main
from notion_agent.notion.client import NotionClient
from tests.fake_notion import FakeNotion, users_me


def _patch_client(monkeypatch: pytest.MonkeyPatch, fake: FakeNotion) -> None:
    monkeypatch.setattr(
        common,
        "build_client",
        lambda: NotionClient("secret-xyz", transport=fake, sleep=lambda s: None),
    )


def test_whoami_missing_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    # The real build_client is in place (no patch), so the missing-token
    # environment error fires end to end.
    rc = main(["whoami"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "NOTION_API_KEY" in err


def test_whoami_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _patch_client(monkeypatch, FakeNotion().standard())
    rc = main(["whoami"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nick: notion-agent" in out
    assert "workspace: Sparkrun" in out
    assert "integration: Spark" in out


def test_whoami_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _patch_client(monkeypatch, FakeNotion().standard())
    rc = main(["whoami", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["nick"] == "notion-agent"
    assert payload["notion"]["workspace"] == "Sparkrun"
    assert payload["notion"]["api_version"]


def test_whoami_owner_workspace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeNotion().on("GET", "/users/me", users_me(owner_type="workspace"))
    _patch_client(monkeypatch, fake)
    rc = main(["whoami"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "integration: Spark (workspace)" in out


def test_whoami_401(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeNotion().on(
        "GET",
        "/users/me",
        (401, {"code": "unauthorized", "message": "API token is invalid.", "request_id": "r1"}),
    )
    _patch_client(monkeypatch, fake)
    rc = main(["whoami"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "r1" in err
    assert "secret-xyz" not in err
