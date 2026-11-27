"""validate-items 的契约测试。"""
import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugin.py"


def _load():
    spec = importlib.util.spec_from_file_location("validate_items_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load()


def test_missing_required_field_is_reported(plugin):
    result = plugin.validate([{"title": "A"}, {"title": ""}], required=["title"])
    assert result["missing"] == [{"index": 1, "fields": ["title"]}]


def test_zero_and_false_are_not_empty(plugin):
    """★ `0` / `False` 是合法数据 —— 把它们当空会让"价格为 0"整行被误报。"""
    result = plugin.validate([{"price": 0, "in_stock": False}], required=["price", "in_stock"])
    assert result["missing"] == []


def test_none_is_empty(plugin):
    result = plugin.validate([{"title": None}], required=["title"])
    assert result["missing"], result


def test_duplicate_key_is_reported_once(plugin):
    items = [{"key": "a"}, {"key": "a"}, {"key": "a"}]
    result = plugin.validate(items, key_field="key")
    assert result["duplicates"] == ["a"]


def test_empty_key_is_not_a_duplicate(plugin):
    """没有键的条目无法判断重复 —— 跳过而不是全算成同一个。"""
    result = plugin.validate([{"key": ""}, {"key": ""}], key_field="key")
    assert result["duplicates"] == []


def test_html_blob_is_suspicious(plugin):
    """★ 整段 HTML 被当标题抓下来 —— 这是最典型的"静默失败"。"""
    result = plugin.validate([{"title": "<html><body>oops</body></html>"}])
    assert result["suspicious"], result
    assert result["suspicious"][0]["reason"]


def test_oversized_field_is_suspicious(plugin):
    result = plugin.validate([{"body": "x" * 200}], max_field_chars=100)
    assert result["suspicious"], result


def test_input_is_not_mutated(plugin):
    items = [{"title": ""}, {"title": "ok"}]
    snapshot = [dict(item) for item in items]
    plugin.validate(items, required=["title"])
    assert items == snapshot


def test_total_counts_only_dict_items(plugin):
    result = plugin.validate([{"a": 1}, "junk", None])
    assert result["total"] == 1


def test_clean_data_has_no_findings(plugin):
    result = plugin.validate([{"key": "a", "title": "ok"}], required=["title"], key_field="key")
    assert not result["missing"] and not result["duplicates"] and not result["suspicious"]


def test_metadata_declares_no_permissions(plugin):
    meta = plugin.PLUGIN_METADATA
    assert meta["permissions"] == []
    assert meta["execution_mode"] == "subprocess"
