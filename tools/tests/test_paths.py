"""P2-7：市场仓自包含路径安全与 ID 正则共享实现负样例回归。"""
from __future__ import annotations

from pathlib import Path

import pytest

from catalog_lib import paths
from validate_submission import safe_rel


@pytest.mark.parametrize("good", ["plugin.py", "config/a.yaml", "tests/test_x.py", "listing.md"])
def test_safe_relative_path_accepted(good: str) -> None:
    assert paths.safe_relative_path(good).as_posix() == good


@pytest.mark.parametrize(
    "bad",
    ["", "a\\b", "/etc/passwd", "../etc/x", "./a.py", "a/../../b", "C:/Windows/x"],
)
def test_safe_relative_path_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        paths.safe_relative_path(bad)


def test_validator_path_helper_matches_shared_rules() -> None:
    """两侧路径规则同集合（投稿器自包含镜像，策略脚本在 CI 锁正则，这里补行为断言）。"""
    for good in ["plugin.py", "config/a.yaml"]:
        assert safe_rel(good).as_posix() == good
    for bad in ["a\\b", "../x", "./a.py"]:
        with pytest.raises(ValueError):
            safe_rel(bad)


@pytest.mark.parametrize("good_id", ["demo", "demo-fetcher", "demo_fetcher", "a1"])
def test_plugin_id_re_accepted(good_id: str) -> None:
    assert paths.PLUGIN_ID_RE.fullmatch(good_id)


@pytest.mark.parametrize("bad_id", ["Demo", "-demo", "demo/", "1demo", "demo..x", ""])
def test_plugin_id_re_rejected(bad_id: str) -> None:
    assert not paths.PLUGIN_ID_RE.fullmatch(bad_id)


@pytest.mark.parametrize(
    "good_id", ["social/market/x", "generic/single-page", "a/b/c"]
)
def test_template_id_re_accepted(good_id: str) -> None:
    assert paths.TEMPLATE_ID_RE.fullmatch(good_id)


@pytest.mark.parametrize(
    "bad_id", ["Social/market", "social//market", "/social", "social/", "social--market"]
)
def test_template_id_re_rejected(bad_id: str) -> None:
    assert not paths.TEMPLATE_ID_RE.fullmatch(bad_id)


def test_template_dir_name_id_roundtrip() -> None:
    assert paths.template_dir_name_to_id("social--market--weibo-search") == "social/market/weibo-search"
    assert paths.template_id_to_dir_name("social/market/weibo-search") == "social--market--weibo-search"
    roundtrip = paths.template_id_to_dir_name(
        paths.template_dir_name_to_id("a--b--c")
    )
    assert roundtrip == "a--b--c"
