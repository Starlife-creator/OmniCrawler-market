"""text-similarity 的契约测试。"""
import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugin.py"


def _load():
    spec = importlib.util.spec_from_file_location("text_similarity_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load()


def test_identical_text_scores_one(plugin):
    assert plugin.similarity("正文", "正文") == 1.0


def test_whitespace_differences_are_not_changes(plugin):
    """★ 排版换行不同不该算变更 —— 这是最常见的假告警源。"""
    assert plugin.similarity("第一行\n\n第二行", "第一行  第二行") == 1.0


def test_both_empty_is_identical(plugin):
    assert plugin.similarity("", "") == 1.0


def test_one_empty_is_completely_different(plugin):
    """★ 空 vs 非空必须是 0.0，不是 1.0（否则"整篇丢了"会被判成没变）。"""
    assert plugin.similarity("", "正文") == 0.0


def test_minor_edit_lands_in_minor_band(plugin):
    before = "这是一段比较长的正文内容，用来测试相似度判定。"
    after = "这是一段比较长的正文内容，用来测试相似度判定了！"
    verdict = plugin.compare_text(before, after)["verdict"]
    assert verdict == "minor", plugin.compare_text(before, after)


def test_completely_different_text_is_changed(plugin):
    result = plugin.compare_text("苹果香蕉", "宇宙飞船")
    assert result["verdict"] == "changed"
    assert result["changed"] is True


def test_identical_threshold_is_configurable(plugin):
    before = "abcdef"
    after = "abcdeg"
    strict = plugin.compare_text(before, after, identical=1.0, minor=0.99)
    assert strict["verdict"] == "changed"


def test_report_includes_lengths(plugin):
    result = plugin.compare_text("abc", "abcd")
    assert result["before_len"] == 3 and result["after_len"] == 4


def test_handle_compares_a_pair(plugin):
    result = plugin.handle("processor.similarity", {"before": "a", "after": "a"})
    assert result["verdict"] == "identical"


def test_metadata_declares_no_permissions(plugin):
    meta = plugin.PLUGIN_METADATA
    assert meta["permissions"] == []
    assert meta["execution_mode"] == "subprocess"
