"""issue-wishlist 的行为测试：stub omnicrawler_sdk，验证只读视图与刷新链路。"""

from __future__ import annotations

import base64
import json
import sys
import types
from pathlib import Path
from runpy import run_path

import pytest


@pytest.fixture()
def plugin(monkeypatch: pytest.MonkeyPatch) -> dict:
    """注入 omnicrawler_sdk stub 后以 run_path 加载插件命名空间（function 级，隔离 _state）。"""
    if "omnicrawler_sdk" not in sys.modules:
        stub = types.ModuleType("omnicrawler_sdk")
        stub.call = lambda *args, **kwargs: {"status": 0, "body_b64": ""}
        monkeypatch.setitem(sys.modules, "omnicrawler_sdk", stub)
    root = Path(__file__).resolve().parents[1]
    return run_path(str(root / "plugin.py"))


def _sdk_with_issues(monkeypatch: pytest.MonkeyPatch, plugin: dict, calls: list) -> None:
    issues = [
        {
            "number": 12,
            "title": "希望支持导出 Parquet",
            "state": "open",
            "html_url": "https://github.com/Starlife-creator/omnicrawler/issues/12",
        },
        {
            "number": 7,
            "title": "坏问题报告模板",
            "state": "open",
            "html_url": "https://github.com/Starlife-creator/omnicrawler/issues/7",
            "pull_request": {"url": "https://api.github.com/repos/x/pulls/7"},
        },
    ]
    body = base64.b64encode(json.dumps(issues).encode("utf-8")).decode("ascii")

    def fake_call(operation: str, payload: dict) -> dict:
        calls.append((operation, payload))
        assert operation == "network.fetch"
        assert payload["url"].startswith("https://api.github.com/repos/Starlife-creator/omnicrawler/issues")
        return {"status": 200, "url": payload["url"], "body_b64": body}

    monkeypatch.setattr(plugin["omnicrawler_sdk"], "call", fake_call)


def test_describe_is_read_only_view(plugin: dict) -> None:
    view = plugin["handle"]("view.describe", {})["view"]
    assert view["view_id"] == "issue-wishlist.main"
    kinds = [c["type"] for c in view["components"]]
    assert kinds == ["rich_text", "button", "resource_list"]
    # 未刷新前不携带数据（安装即用、不自动联网）
    assert view["components"][2]["items"] == []


def test_refresh_fetches_and_filters_prs(monkeypatch: pytest.MonkeyPatch, plugin: dict) -> None:
    calls: list = []
    _sdk_with_issues(monkeypatch, plugin, calls)
    result = plugin["handle"]("view.action", {"action": "refresh", "payload": {}})
    assert "已刷新：1 个开放 Issues" in result["message"]  # PR（#7）被过滤
    listing = result["view"]["components"][2]
    assert listing["items"][0]["label"].startswith("#12 ")


def test_open_issue_returns_link(monkeypatch: pytest.MonkeyPatch, plugin: dict) -> None:
    calls: list = []
    _sdk_with_issues(monkeypatch, plugin, calls)
    plugin["handle"]("view.action", {"action": "refresh", "payload": {}})
    result = plugin["handle"](
        "view.action", {"action": "open-issue", "payload": {"item_id": "12"}}
    )
    assert "issues/12" in result["message"]
    expired = plugin["handle"](
        "view.action", {"action": "open-issue", "payload": {"item_id": "999"}}
    )
    assert "过期" in expired["message"]


def test_refresh_failure_shows_error_in_panel(
    monkeypatch: pytest.MonkeyPatch, plugin: dict
) -> None:
    def broken_call(operation: str, payload: dict) -> dict:
        assert operation == "network.fetch"
        return {"status": 403, "url": payload["url"], "body_b64": ""}

    monkeypatch.setattr(plugin["omnicrawler_sdk"], "call", broken_call)
    result = plugin["handle"]("view.action", {"action": "refresh", "payload": {}})
    assert "403" in result["message"]
    segments = result["view"]["components"][0]["segments"]
    assert any("403" in s.get("text", "") for s in segments)
