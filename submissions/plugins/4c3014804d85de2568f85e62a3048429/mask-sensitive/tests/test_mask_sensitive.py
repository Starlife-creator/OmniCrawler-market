"""mask-sensitive 的契约测试。"""
import importlib.util
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugin.py"


def _load():
    spec = importlib.util.spec_from_file_location("mask_sensitive_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def plugin():
    return _load()


def test_email_is_masked(plugin):
    item, hits = plugin.mask_item({"contact": "alice@example.com"})
    assert "alice@" not in str(item["contact"])
    assert hits


def test_mask_is_not_a_plaintext_leak(plugin):
    """★ 掩码后的值里不许残留原文（否则等于没脱敏）。"""
    original = "13800138000"
    item, _ = plugin.mask_item({"phone": original})
    assert original not in str(item["phone"])


def test_allowlisted_field_is_not_masked(plugin):
    """`order_id` 这类业务标识不该被误伤。"""
    item, hits = plugin.mask_item({"order_id": "12345678901"})
    assert item["order_id"] == "12345678901"
    assert not hits


def test_password_field_is_masked_even_if_content_looks_normal(plugin):
    """★ 字段名命中敏感词时整值脱敏，哪怕内容不像任何模式。"""
    item, hits = plugin.mask_item({"password": "short"})
    assert item["password"] != "short"
    assert hits


def test_input_is_not_mutated(plugin):
    """纯函数：不修改入参。"""
    original = {"email": "a@b.co"}
    snapshot = dict(original)
    plugin.mask_item(original)
    assert original == snapshot


def test_short_value_is_fully_masked(plugin):
    """短值不能"保留首尾各 3 位"——那样等于原样返回。"""
    masked = plugin._mask_value("abc")
    assert set(masked) == {"*"}


def test_hash_is_stable_for_same_secret_and_value(plugin):
    a = plugin._hash_value("x", "s")
    b = plugin._hash_value("x", "s")
    assert a == b and a.startswith("h:")


def test_hash_differs_with_different_secret(plugin):
    """★ 不同密钥必须给出不同哈希 —— 否则密钥形同虚设。"""
    assert plugin._hash_value("x", "s1") != plugin._hash_value("x", "s2")


def test_handle_dispatches_both_operations(plugin):
    result = plugin.handle("processor.mask", {"items": [{"email": "a@b.co"}]})
    assert "items" in result
    hook = plugin.handle("hook.before_export", {"items": [{"email": "a@b.co"}]})
    assert "items" in hook


def test_metadata_declares_no_permissions(plugin):
    meta = plugin.PLUGIN_METADATA
    assert meta["permissions"] == []
    assert meta["execution_mode"] == "subprocess"
