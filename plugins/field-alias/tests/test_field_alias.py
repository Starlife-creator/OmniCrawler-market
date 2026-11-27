"""field-alias 的契约测试（可在沙箱外用 pytest 直接跑）。"""
import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugin.py"


def _load():
    spec = importlib.util.spec_from_file_location("field_alias_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load()


def test_merges_synonyms_into_one_column(plugin):
    items = [
        {"标题": "A", "价格": "1"},
        {"名称": "B", "价格": "2"},
        {"title": "C", "价格": "3"},
    ]
    result = plugin.apply_aliases(items, {"商品名": ["标题", "名称", "title"]})
    assert [row["商品名"] for row in result["items"]] == ["A", "B", "C"]
    assert result["renamed"]["商品名"] == ["名称", "标题", "title"] or set(result["renamed"]["商品名"]) == {"标题", "名称", "title"}


def test_target_column_wins_over_aliases(plugin):
    """目标列本来就有值时不许被别名覆盖。"""
    items = [{"商品名": "canonical", "标题": "other"}]
    result = plugin.apply_aliases(items, {"商品名": ["标题"]})
    assert result["items"][0]["商品名"] == "canonical"


def test_blank_values_do_not_count_as_present(plugin):
    """空白（None/空串/纯空白/空列表）不算"有值"。"""
    items = [{"目标": None, "别名": "  "}, {"目标": "", "别名": "real"}]
    result = plugin.apply_aliases(items, {"目标": ["别名"]})
    assert result["items"][1]["目标"] == "real"
    assert result["items"][0]["目标"] in (None, "")


def test_conflict_is_reported_not_silently_dropped(plugin):
    """两个别名同时有不同值 ⇒ 必须写进 conflicts。"""
    items = [{"标题": "A", "名称": "B"}]
    result = plugin.apply_aliases(items, {"商品名": ["标题", "名称"]})
    assert result["conflicts"], result
    assert result["conflicts"][0]["index"] == 0
    assert set(result["conflicts"][0]["values"]) == {"标题", "名称"}
    # 仍然要产出一个值（第一个非空）
    assert result["items"][0]["商品名"] == "A"


def test_identical_values_are_not_a_conflict(plugin):
    """两个别名值相同不算冲突（否则跨站同值会刷一屏噪声）。"""
    items = [{"标题": "same", "名称": "same"}]
    result = plugin.apply_aliases(items, {"商品名": ["标题", "名称"]})
    assert result["conflicts"] == []


def test_source_columns_are_kept_by_default(plugin):
    """默认不删原列 —— 用户要能回查原始数据。"""
    items = [{"标题": "A"}]
    result = plugin.apply_aliases(items, {"商品名": ["标题"]})
    assert result["items"][0]["标题"] == "A"
    assert result["items"][0]["商品名"] == "A"


def test_drop_source_removes_aliases_only(plugin):
    items = [{"标题": "A", "价格": "1"}]
    result = plugin.apply_aliases(items, {"商品名": ["标题"]}, drop_source=True)
    row = result["items"][0]
    assert "标题" not in row
    assert row["价格"] == "1"
    assert row["商品名"] == "A"


def test_empty_spec_is_a_noop(plugin):
    items = [{"a": 1}]
    result = plugin.apply_aliases(items, {})
    assert result["items"] == items
    assert result["conflicts"] == []


def test_non_dict_items_are_passed_through(plugin):
    items = ["not a dict", 42, None]
    result = plugin.apply_aliases(items, {"x": ["y"]})
    assert result["items"] == items


def test_handle_dispatches_processor_alias(plugin):
    payload = {"items": [{"标题": "A"}], "config": {"aliases": {"商品名": ["标题"]}}}
    result = plugin.handle("processor.alias", payload)
    assert result["items"][0]["商品名"] == "A"
    assert "summary" in result


def test_handle_ignores_unknown_operation(plugin):
    assert plugin.handle("processor.other", {}) == {"operation": "processor.other"}


def test_metadata_is_ast_literal_and_declares_no_permissions(plugin):
    """市场门禁要求 PLUGIN_METADATA 可由 AST 字面量读取，且最小权限。"""
    meta = plugin.PLUGIN_METADATA
    assert meta["plugin_types"] == ["processor", "transformer"]
    assert meta["permissions"] == []
    assert meta["execution_mode"] == "subprocess"
