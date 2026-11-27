"""diff-report 的契约测试。"""
import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugin.py"


def _load():
    spec = importlib.util.spec_from_file_location("diff_report_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load()


def test_detects_added_removed_changed(plugin):
    previous = [{"key": "a", "v": 1}, {"key": "b", "v": 2}]
    current = [{"key": "b", "v": 3}, {"key": "c", "v": 4}]
    result = plugin.diff(previous, current)
    assert result["added"] == ["c"]
    assert result["removed"] == ["a"]
    assert result["changed"] == [{"key": "b", "fields": ["v"]}]


def test_ignored_fields_do_not_create_noise(plugin):
    """★ fetched_at 每次都变；不忽略它会让所有条目都报「修改」。"""
    previous = [{"key": "a", "v": 1, "fetched_at": "2026-01-01"}]
    current = [{"key": "a", "v": 1, "fetched_at": "2026-02-02"}]
    result = plugin.diff(previous, current, ignore=["fetched_at"])
    assert result["changed"] == []


def test_without_ignore_the_volatile_field_does_show_up(plugin):
    """反方向：不忽略时它**应该**被报出来（否则 ignore 是假功能）。"""
    previous = [{"key": "a", "fetched_at": "2026-01-01"}]
    current = [{"key": "a", "fetched_at": "2026-02-02"}]
    result = plugin.diff(previous, current)
    assert result["changed"] == [{"key": "a", "fields": ["fetched_at"]}]


def test_items_without_a_key_are_skipped(plugin):
    """没有稳定键就无法对比 —— 跳过而不是猜。"""
    result = plugin.diff([{"v": 1}], [{"key": "a", "v": 2}], key_field="key")
    assert result["counts"]["previous"] == 0
    assert result["added"] == ["a"]


def test_underscore_prefixed_fields_are_ignored(plugin):
    """内部字段（_item 之类）不该参与比较。"""
    result = plugin.diff(
        [{"key": "a", "_item": 1}], [{"key": "a", "_item": 2}],
    )
    assert result["changed"] == []


def test_field_appearing_or_disappearing_counts_as_change(plugin):
    result = plugin.diff([{"key": "a", "x": 1}], [{"key": "a", "x": 1, "y": 2}])
    assert result["changed"] == [{"key": "a", "fields": ["y"]}]


def test_counts_are_accurate(plugin):
    previous = [{"key": str(i), "v": i} for i in range(3)]
    current = [{"key": str(i), "v": i} for i in range(1, 4)]
    counts = plugin.diff(previous, current)["counts"]
    assert counts == {"previous": 3, "current": 3, "added": 1, "removed": 1, "changed": 0}


def test_summary_line_is_readable(plugin):
    # `diff()` 本身不写 summary（那是 handle 的职责），summary_line 单独可调 ——
    # 这样纯函数保持"只算数据"，给人看的文案不混进数据结构。
    result = plugin.diff([{"key": "a"}], [{"key": "b"}])
    text = plugin.summary_line(result)
    assert "新增 1" in text
    assert "删除 1" in text


def test_handle_dispatches_processor_diff(plugin):
    result = plugin.handle("processor.diff", {
        "previous": [{"key": "a"}], "current": [{"key": "b"}],
        "config": {"key_field": "key"},
    })
    assert result["added"] == ["b"]
    assert "summary" in result


def test_handle_ignores_unknown_operation(plugin):
    assert plugin.handle("processor.other", {}) == {"operation": "processor.other"}


def test_metadata_declares_no_permissions(plugin):
    meta = plugin.PLUGIN_METADATA
    assert meta["permissions"] == []
    assert meta["execution_mode"] == "subprocess"
