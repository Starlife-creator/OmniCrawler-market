"""csv-io 的契约测试（可在沙箱外直接跑）。"""
import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugin.py"


def _load():
    spec = importlib.util.spec_from_file_location("csv_io_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load()


def test_export_writes_bom_by_default(plugin):
    """★ Excel 靠 BOM 判定 UTF-8 —— 没有它，中文版 Excel 打开就是乱码。"""
    result = plugin.to_csv([{"名称": "书"}])
    assert result["text"].startswith("\ufeff")
    assert "名称" in result["text"]


def test_bom_can_be_disabled(plugin):
    result = plugin.to_csv([{"a": "1"}], bom=False)
    assert not result["text"].startswith("\ufeff")


def test_newlines_and_commas_survive_roundtrip(plugin):
    """★ 正文含换行/逗号/引号时，结构必须完好 —— 这是手拼字符串必翻车的地方。"""
    rows = [{"标题": 'a,b', "正文": "line1\nline2", "引用": 'he said "hi"'}]
    exported = plugin.to_csv(rows, bom=False)
    parsed = plugin.from_csv(exported["text"])
    assert parsed["items"] == rows


def test_formula_injection_is_neutralised(plugin):
    """★ 以公式字符开头的单元格必须加前缀，否则打开就外联。

    判据走**解析回来**而不是原始字符串：单元格含引号/逗号时 csv 会给整格加引号
    并把内部引号翻倍，直接比子串会假红（我第一版就写错过）。
    """
    for payload in ("=HYPERLINK(\"http://evil\",\"x\")", "+1+1", "-1+1", "@SUM(A1)"):
        result = plugin.to_csv([{"v": payload}], bom=False)
        parsed = plugin.from_csv(result["text"])
        assert parsed["items"][0]["v"] == "'" + payload, payload


def test_formula_sanitising_can_be_disabled(plugin):
    result = plugin.to_csv([{"v": "=1+1"}], bom=False, sanitize=False)
    assert "'=1+1" not in result["text"]


def test_plain_numbers_are_not_mangled(plugin):
    result = plugin.to_csv([{"v": "42"}], bom=False)
    assert "'42" not in result["text"]


def test_field_order_is_first_seen(plugin):
    """列顺序按**首次出现**，保证同一批数据的 diff 稳定。"""
    result = plugin.to_csv([{"b": "1", "a": "2"}, {"a": "3", "c": "4"}], bom=False)
    assert result["fields"] == ["b", "a", "c"]


def test_missing_keys_become_empty(plugin):
    result = plugin.to_csv([{"a": "1", "b": "2"}, {"a": "3"}], bom=False)
    lines = result["text"].strip().split("\r\n")
    assert lines[1] == "1,2"
    assert lines[2] == "3,"


def test_non_dict_items_are_skipped(plugin):
    result = plugin.to_csv([{"a": "1"}, "junk", None], bom=False)
    assert result["count"] == 1


def test_empty_input_returns_empty_text(plugin):
    assert plugin.to_csv([])["text"] == ""
    assert plugin.to_csv([])["count"] == 0


def test_from_csv_tolerates_bom(plugin):
    parsed = plugin.from_csv("\ufeffa,b\r\n1,2\r\n")
    assert parsed["items"] == [{"a": "1", "b": "2"}]


def test_handle_dispatches_both_operations(plugin):
    exported = plugin.handle("exporter.csv", {"items": [{"a": "1"}]})
    assert exported["extension"] == "csv"
    assert exported["count"] == 1
    parsed = plugin.handle("processor.csv-parse", {"text": exported["text"]})
    assert parsed["items"] == [{"a": "1"}]


def test_handle_ignores_unknown_operation(plugin):
    assert plugin.handle("exporter.other", {}) == {"operation": "exporter.other"}


def test_metadata_declares_no_permissions(plugin):
    meta = plugin.PLUGIN_METADATA
    assert meta["permissions"] == []
    assert meta["execution_mode"] == "subprocess"
    assert meta["dependencies"] == []
