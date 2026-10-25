"""P1-4：发现页渲染转义负样例——脚本标签、属性突破、引号/尖括号注入不得原样落地。"""
from __future__ import annotations

import pytest

from generate_discovery_page import _esc


@pytest.mark.parametrize(
    "raw",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        '"><svg onload=alert(1)>',
        "<a href='javascript:evil'>x</a>",
        "<!-- comment --><script>steal()</script>",
    ],
)
def test_injection_payloads_are_escaped(raw: str) -> None:
    rendered = _esc(raw)
    assert "<script" not in rendered.lower()
    assert "<img" not in rendered.lower()
    assert "<svg" not in rendered.lower()
    assert rendered != raw


def test_quote_characters_escaped_for_attributes() -> None:
    rendered = _esc('" onmouseover="alert(1)')
    assert "&quot;" in rendered
    assert '"' not in rendered


def test_javascript_scheme_text_is_not_html_payload() -> None:
    # 纯方案名不含 HTML 元字符；URL  scheme 白名单属链接层独立校验。
    rendered = _esc("javascript:alert(1)")
    assert rendered == "javascript:alert(1)"


def test_none_renders_empty_string() -> None:
    assert _esc(None) == ""


def test_plain_text_preserved() -> None:
    assert _esc("网络采集处理器") == "网络采集处理器"
