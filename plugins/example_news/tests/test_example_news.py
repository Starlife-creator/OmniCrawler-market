"""example_news 的契约测试（同时是"契约 2 插件怎么写对"的活的说明）。"""
import ast
import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugin.py"


def _load():
    spec = importlib.util.spec_from_file_location("example_news_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load()


def test_seeds_become_requests_with_the_required_header(plugin):
    result = plugin.handle("source.seed", {"config": {"seeds": ["https://example.org/"]}})
    assert len(result["requests"]) == 1
    assert result["requests"][0]["headers"]["X-Requested-With"] == "XMLHttpRequest"


def test_dict_seed_keeps_its_own_method_and_headers(plugin):
    result = plugin.handle("source.seed", {
        "config": {"seeds": [{"url": "https://example.org/a", "method": "POST",
                             "headers": {"X-Test": "1"}}]},
    })
    req = result["requests"][0]
    assert req["method"] == "POST"
    assert req["headers"]["X-Test"] == "1"


def test_empty_seed_is_skipped(plugin):
    """空 URL 不产生请求（而不是产生一条 url="" 的假请求）。"""
    assert plugin.handle("source.seed", {"config": {"seeds": ["", None]}})["requests"] == []


def test_unknown_operation_is_echoed_not_raised(plugin):
    """宿主可能对所有插件广播同一批操作 —— 不认识的要安静回显。"""
    assert plugin.handle("processor.other", {}) == {"operation": "processor.other"}


def test_plugin_does_not_import_omnicrawler(plugin):
    """★ 契约 2 硬规矩：不能 import omnicrawler。用 AST 静态检查，不看运行时。"""
    tree = ast.parse(PLUGIN.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "omnicrawler" not in imported, imported


def test_metadata_is_a_static_literal(plugin):
    """★ 市场门禁要求 PLUGIN_METADATA 可由 AST 字面量读出（不能用变量拼）。"""
    tree = ast.parse(PLUGIN.read_text(encoding="utf-8"))
    found = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PLUGIN_METADATA":
                    assert isinstance(node.value, ast.Dict), "PLUGIN_METADATA 必须是字面量 dict"
                    found = True
    assert found, "缺少 PLUGIN_METADATA"


def test_metadata_declares_no_permissions(plugin):
    """样板示范最小权限：只产生请求描述，所以是空列表。"""
    meta = plugin.PLUGIN_METADATA
    assert meta["permissions"] == []
    assert meta["execution_mode"] == "subprocess"


def test_no_network_module_is_imported(plugin):
    """★ 插件不自己发请求 —— 模块级不许导入网络库。"""
    source = PLUGIN.read_text(encoding="utf-8")
    for module in ("socket", "urllib.request", "http.client", "requests", "httpx"):
        assert f"import {module}" not in source, module
