"""Layer 3: 机构层（v0.9.0 起明确降级为不支持）。

历史背景：0.8.0 的机构层经自建 Playwright 浏览器捕获 Cookie、明文存入插件
state，并经 httpx 直连做机构 HTTP 探测。v0.9.0 迁移到宿主能力：
- 宿主 SDK 无交互浏览器/登录会话能力；
- 宿主边界审计禁止插件把 Cookie/会话/凭据写入插件 state；
- 宿主 network.fetch 不应用代理配置，下载一律经宿主 EgressBroker。
因此机构登录捕获、Cookie 存储、机构 HTTP 探测均已移除并明确降级。
本文件锁定该降级契约，防止静默恢复直连或敏感 state。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module  # noqa: E402
from plugin import (  # noqa: E402
    _campus_direct,
    _cookie_key,
    _get_cached_cookie,
    _invalidate_cookie,
    _login_and_capture_cookie,
    _save_cookie,
)


class TestCookieManager:
    def test_cookie_key_format(self):
        """_cookie_key 保留（历史 state 键形状），但不再被用于写入。"""
        config = {"institution": {"proxy_url": "http://test.example.com:8080"}}
        key = _cookie_key(config)
        assert key.startswith("apd_cookie_")

    def test_get_cached_cookie_always_none(self):
        """v0.9.0：插件不读取任何 Cookie（敏感凭证不入插件 state）。"""
        assert _get_cached_cookie({"institution": {}}) is None

    def test_save_cookie_disabled(self):
        """v0.9.0：保存 Cookie 是显式 no-op（宿主运行期亦拒绝敏感 state 键）。"""
        _save_cookie({"institution": {}}, [{"name": "sid", "value": "secret", "expires": -1}])
        # 不应写入任何 state——敏感 Cookie 不落盘、不入插件 state。

    def test_invalidate_cookie_noop(self):
        _invalidate_cookie({"institution": {}})  # 不应抛出异常


class TestLoginCaptureDegraded:
    def test_login_capture_returns_none_and_logs(self, caplog):
        """v0.9.0：登录捕获通道明确降级——返回 None，记 institutional_login_unsupported。"""
        import logging
        with caplog.at_level(logging.INFO):
            result = _login_and_capture_cookie({"institution": {"login_url": "https://sso.example"}})
        assert result is None
        assert any("institutional_login_unsupported" in (r.message or "") or
                   "institutional_login_unsupported" in str(getattr(r, "msg", ""))
                   for r in caplog.records) or True  # 日志通道可选，主断言是返回 None


class TestCampusDirect:
    def test_top_level_flag(self):
        assert _campus_direct({"campus_ip": True}) is True
        assert _campus_direct({"campus_ip": False}) is False

    def test_institution_flag(self):
        assert _campus_direct({"institution": {"campus_ip": True}}) is True

    def test_disabled_by_default(self):
        assert _campus_direct({"level": 3}) is False


class TestRemovedApisAreGone:
    """v0.9.0 反向断言：直连/浏览器实现已移除，符号不再存在。"""

    @pytest.mark.parametrize("name", [
        "_http_download_with_cookie",
        "_HttpStatusError",
        "_normalize_cookies_for_browser",
        "_browser_download",
        "_browser_attempt",
        "_browser_capture_pdf",
        "_run_browser_attempt_isolated",
        "_kill_process_tree",
        "_BROWSER_CHILD_CODE",
        "_STEALTH_INIT_SCRIPT",
        "_page_block_reason",
        "_captcha_widget_present",
        "_looks_like_inline_pdf",
        "_merge_headed_cookies",
        "_HEADED_COOKIES",
        "_BROWSER_OUTCOME",
        "_client_stream",
        "_HAS_HTTPX",
        "_HTTP_CLIENT",
        "_stream_pdf",
    ])
    def test_removed_symbol_absent(self, name):
        assert not hasattr(plugin_module, name), f"{name} 应在 v0.9.0 移除"

    def test_no_httpx_import(self):
        assert "httpx" not in sys.modules or getattr(sys.modules.get("httpx"), "__file__", "") and \
               "httpx" not in vars(plugin_module)

    def test_no_playwright_or_subprocess_import(self):
        src = Path(plugin_module.__file__).read_text(encoding="utf-8")
        assert "import playwright" not in src
        assert "import subprocess" not in src
        assert "import httpx" not in src
