"""P1-4：投稿校验器 ID / 用户名 / 域名 / 相对路径格式边界负样例（纯函数层）。"""
from __future__ import annotations

import pytest

import validate_submission as validator


# --- 插件 ID ------------------------------------------------------------------
@pytest.mark.parametrize("bad_id", ["1demo", "-demo", "Demo", "_demo", ""])
def test_plugin_id_rejected(bad_id: str) -> None:
    assert validator.PLUGIN_ID_RE.fullmatch(bad_id) is None


@pytest.mark.parametrize("good_id", ["demo", "demo-processor", "demo_processor", "a1"])
def test_plugin_id_accepted(good_id: str) -> None:
    assert validator.PLUGIN_ID_RE.fullmatch(good_id)


# --- 模板 ID（层级 + 段内单连字符/下划线） --------------------------------------
@pytest.mark.parametrize(
    "bad_id", ["1demo", "-demo", "Demo", "demo--x", "/demo", "demo/", "demo//x", "demo_.x"]
)
def test_template_id_rejected(bad_id: str) -> None:
    assert validator.TEMPLATE_ID_RE.fullmatch(bad_id) is None


@pytest.mark.parametrize("good_id", ["generic/single-page", "a/b/c", "source_parser"])
def test_template_id_accepted(good_id: str) -> None:
    assert validator.TEMPLATE_ID_RE.fullmatch(good_id)


# --- 用户名 -------------------------------------------------------------------
@pytest.mark.parametrize("bad_name", ["A", "alice!", "alice 01", "x" * 33, ""])
def test_username_rejected(bad_name: str) -> None:
    assert validator.USERNAME_RE.fullmatch(bad_name) is None


@pytest.mark.parametrize("good_name", ["alice", "alice-01", "alice_01", "ab"])
def test_username_accepted(good_name: str) -> None:
    assert validator.USERNAME_RE.fullmatch(good_name)


# --- 域名 ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_domain",
    ["-example.com", "example..com", "example.", ".example.com", "example com", "example_.com"],
)
def test_domain_rejected(bad_domain: str) -> None:
    assert validator.DOMAIN_RE.fullmatch(bad_domain) is None


@pytest.mark.parametrize("good_domain", ["example.com", "api.example.co.uk", "a-b.example.org"])
def test_domain_accepted(good_domain: str) -> None:
    assert validator.DOMAIN_RE.fullmatch(good_domain)


# --- 相对路径安全（P2-7 镜像规则） ----------------------------------------------
@pytest.mark.parametrize(
    "bad_path", ["/etc/passwd", "..", "../plugin.py", "a/../b.py", "a/./b.py", "plugins\\x.py", "C:/x"]
)
def test_safe_rel_rejects_unsafe_paths(bad_path: str) -> None:
    with pytest.raises(ValueError):
        validator.safe_rel(bad_path)


def test_safe_rel_accepts_plain_relative() -> None:
    assert str(validator.safe_rel("plugins/demo/plugin.py")) == "plugins/demo/plugin.py"


def test_canonical_is_deterministic() -> None:
    left = validator.canonical({"b": 2, "a": 1})
    right = validator.canonical({"a": 1, "b": 2})
    assert left == right
    assert left.endswith(b"\n")
