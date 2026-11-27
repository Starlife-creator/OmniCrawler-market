"""export-jsonl 的契约测试。"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugin.py"


def _load():
    spec = importlib.util.spec_from_file_location("export_jsonl_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load()


def test_one_line_per_record(plugin):
    result = plugin.to_jsonl([{"a": 1}, {"b": 2}])
    lines = result["text"].strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"a": 1}


def test_output_ends_with_newline(plugin):
    """JSONL 规范：最后一行也要有换行，否则 `cat` 后接命令会粘连。"""
    assert plugin.to_jsonl([{"a": 1}])["text"].endswith("\n")


def test_chinese_is_not_escaped(plugin):
    """`ensure_ascii=False`：中文原样输出，文件更小、可读性更好。"""
    assert "中文" in plugin.to_jsonl([{"v": "中文"}])["text"]


def test_compact_separators(plugin):
    """紧凑分隔符：不写 `", "` / `": "` 的空格，文件更小。"""
    assert '{"a":1}' in plugin.to_jsonl([{"a": 1}])["text"]


def test_oversized_line_is_skipped_and_reported(plugin):
    """★ 超长行必须**跳过并回报**，不能静默丢弃。"""
    big = {"v": "x" * 2000}
    result = plugin.to_jsonl([{"a": 1}, big], max_line_bytes=500)
    assert result["count"] == 1
    assert result["skipped"] == 1


def test_empty_input_yields_empty_text(plugin):
    result = plugin.to_jsonl([])
    assert result["text"] == "" and result["count"] == 0


def test_handle_dispatches_exporter_jsonl(plugin):
    result = plugin.handle("exporter.jsonl", {"items": [{"a": 1}]})
    assert result["extension"] == "jsonl"
    assert result["media_type"] == "application/x-ndjson"


def test_handle_ignores_unknown_operation(plugin):
    assert plugin.handle("exporter.csv", {}) == {"operation": "exporter.csv"}


def test_metadata_declares_no_permissions(plugin):
    meta = plugin.PLUGIN_METADATA
    assert meta["permissions"] == []
    assert meta["execution_mode"] == "subprocess"
