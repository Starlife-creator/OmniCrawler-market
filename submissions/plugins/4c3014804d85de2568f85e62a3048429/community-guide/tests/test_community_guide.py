"""community-guide 的行为测试：纯静态引导、零网络、外链段合规。"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from runpy import run_path

import pytest


@pytest.fixture()
def plugin(monkeypatch: pytest.MonkeyPatch) -> dict:
    if "omnicrawler_sdk" not in sys.modules:
        stub = types.ModuleType("omnicrawler_sdk")
        stub.call = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("纯静态插件不得调用任何宿主能力")
        )
        monkeypatch.setitem(sys.modules, "omnicrawler_sdk", stub)
    root = Path(__file__).resolve().parents[1]
    return run_path(str(root / "plugin.py"))


def test_view_is_static_link_panel(plugin: dict) -> None:
    view = plugin["handle"]("view.describe", {})["view"]
    assert view["view_id"] == "community-guide.main"
    (component,) = view["components"]
    assert component["type"] == "rich_text"
    links = [s for s in component["segments"] if s["type"] == "link"]
    assert len(links) == 4
    assert all(s["url"].startswith("https://github.com/Starlife-creator/omnicrawler") for s in links)


def test_metadata_declares_zero_network(plugin: dict) -> None:
    meta = plugin["PLUGIN_METADATA"]
    assert meta["permissions"] == []
    assert meta["domains"] == []
    assert "network.fetch" not in meta["required_capabilities"]
    assert meta["required_capabilities"] == {"view.richtext": ">=1"}


def test_unknown_operation_is_noop(plugin: dict) -> None:
    assert plugin["handle"]("view.action", {"action": "anything"}) == {"handled": False}
