"""notify-webhook 的契约测试。"""
import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugin.py"


def _load():
    spec = importlib.util.spec_from_file_location("notify_webhook_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load()


def test_no_url_means_no_request(plugin):
    """★ 没配置就不发 —— 可选能力缺配置是正常状态，不是错误。"""
    result = plugin.handle("hook.task_finished", {"config": {}, "task": {"status": "succeeded"}})
    assert result["requests"] == []
    assert "未配置" in result["skipped"]


def test_terminal_status_produces_one_request(plugin):
    payload = {
        "config": {"url": "https://example.org/hook"},
        "task": {"id": "t-1", "status": "succeeded"},
        "stats": {"succeeded": 5, "failed": 1, "skipped": 2},
    }
    result = plugin.handle("hook.task_finished", payload)
    assert len(result["requests"]) == 1
    req = result["requests"][0]
    assert req["url"] == "https://example.org/hook"
    assert req["method"] == "POST"
    assert req["json"]["summary"]["succeeded"] == 5


def test_non_terminal_status_is_skipped(plugin):
    """★ running/pending/queued 不打扰用户。"""
    for status in ("running", "pending", "queued"):
        result = plugin.handle("hook.task_finished", {
            "config": {"url": "https://example.org/hook"},
            "task": {"id": "t", "status": status},
        })
        assert result["requests"] == [], status


def test_only_terminal_can_be_disabled(plugin):
    """反方向：`only_terminal: false` 时非终态也要推。"""
    result = plugin.handle("hook.task_finished", {
        "config": {"url": "https://example.org/hook", "only_terminal": False},
        "task": {"id": "t", "status": "running"},
    })
    assert len(result["requests"]) == 1


def test_plugin_never_returns_a_raw_http_call(plugin):
    """★ 硬边界：返回值里只能有**请求描述**，不能有已发生的调用痕迹。

    判据：请求描述是纯数据（可 json 序列化），不含 socket / response 对象。
    """
    import json

    result = plugin.handle("hook.task_finished", {
        "config": {"url": "https://example.org/hook"},
        "task": {"id": "t", "status": "succeeded"},
    })
    json.dumps(result)  # 不可序列化就说明混进了运行时对象


def test_missing_fields_get_safe_defaults(plugin):
    """缺字段时给安全默认值，不抛异常。"""
    result = plugin.handle("hook.task_finished", {"config": {"url": "https://example.org/h"}})
    summary = result["requests"][0]["json"]["summary"]
    assert summary["status"] == "unknown"
    assert summary["succeeded"] == 0


def test_summary_line_is_readable(plugin):
    text = plugin._render_text({
        "task_id": "t-9", "status": "failed", "succeeded": 0, "failed": 3, "skipped": 0,
    })
    assert "t-9" in text and "失败 3" in text


def test_unknown_operation_is_echoed(plugin):
    assert plugin.handle("hook.other", {}) == {"operation": "hook.other"}


def test_metadata_declares_no_permissions(plugin):
    meta = plugin.PLUGIN_METADATA
    assert meta["permissions"] == []
    assert meta["execution_mode"] == "subprocess"
