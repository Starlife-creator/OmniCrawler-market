"""Layer 3: 机构代理测试。"""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module
from plugin import (
    _get_cached_cookie, _save_cookie, _invalidate_cookie, _cookie_key,
    _normalize_cookies_for_browser, _campus_direct,
    _http_download_with_cookie, _HttpStatusError,
)


class TestCookieManager:
    def test_cookie_key_format(self):
        config = {"institution": {"proxy_url": "http://test.example.com:8080"}}
        key = _cookie_key(config)
        assert key.startswith("apd_cookie_")

    def test_get_cached_cookie_no_sdk(self):
        result = _get_cached_cookie({"institution": {}})
        assert result is None

    def test_invalidate_cookie_no_sdk(self):
        _invalidate_cookie({"institution": {}})  # 不应抛出异常


class TestCampusDirect:
    def test_top_level_flag(self):
        assert _campus_direct({"campus_ip": True}) is True
        assert _campus_direct({"campus_ip": False}) is False

    def test_institution_flag(self):
        assert _campus_direct({"institution": {"campus_ip": True}}) is True

    def test_disabled_by_default(self):
        assert _campus_direct({"level": 3}) is False


class TestNormalizeCookiesForBrowser:
    def test_playwright_cookies_kept(self):
        ck = [{"name": "sid", "value": "abc", "domain": ".mdpi.com", "path": "/"}]
        out = _normalize_cookies_for_browser(ck, "https://www.mdpi.com")
        assert out == ck

    def test_adds_home_url_when_missing_domain(self):
        out = _normalize_cookies_for_browser(
            [{"name": "sid", "value": "abc"}], "https://www.mdpi.com")
        assert out[0]["url"] == "https://www.mdpi.com"
        assert out[0]["path"] == "/"

    def test_drops_invalid_entries(self):
        out = _normalize_cookies_for_browser(
            [{"name": "sid", "value": "abc"},
             None,
             {"value": "no-name"},
             {"name": "x"}], "https://x.test")
        assert len(out) == 1

    def test_keeps_existing_domain_and_path(self):
        out = _normalize_cookies_for_browser(
            [{"name": "sid", "value": "abc", "domain": ".springer.com"}], "https://link.springer.com")
        assert out[0]["domain"] == ".springer.com"
        assert out[0]["path"] == "/"


class _ProbeResp:
    """只暴露 headers/status/history，任何正文读取都直接失败——确保只做无正文探测。"""

    def __init__(self, status, content_type, history=()):
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.history = history
        read_guard = object()
        self._guard = read_guard

    @property
    def content(self):
        raise AssertionError("不应下载响应正文")

    def read(self):
        raise AssertionError("不应下载响应正文")

    def iter_bytes(self):
        raise AssertionError("不应下载响应正文")

    def iter_raw(self):
        raise AssertionError("不应下载响应正文")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestHttpProbe:
    """Layer 3 机构 HTTP 层：只读响应头探测，不做成双重下载。"""

    def _mock_client(self, monkeypatch, response):
        """把共享 HTTP 客户端替换为返回指定响应的 mock。"""
        mock_client = type("MockClient", (), {
            "stream": lambda *a, **k: response,
            "is_closed": False,
        })()
        monkeypatch.setattr(plugin_module, "_HTTP_CLIENT", mock_client)

    def test_pdf_200_returns_url(self, monkeypatch):
        self._mock_client(monkeypatch, _ProbeResp(200, "application/pdf"))
        url = _http_download_with_cookie("10.3390/ma16010001", "mdpi",
                                         {"sid": "x"}, {"institution": {}})
        assert url == "https://www.mdpi.com/10.3390/ma16010001/pdf"

    def test_subscription_403_surfaces_status_and_invalidates(self, monkeypatch):
        invalidated = {"n": 0}
        monkeypatch.setattr(plugin_module, "_invalidate_cookie",
                            lambda c: invalidated.__setitem__("n", invalidated["n"] + 1))
        self._mock_client(monkeypatch, _ProbeResp(403, "text/html"))

        with pytest.raises(_HttpStatusError) as exc:
            _http_download_with_cookie("10.1016/j.body.2023.1", "elsevier",
                                       {}, {"institution": {}})
        assert exc.value.status == 403
        assert invalidated["n"] == 1

    def test_free_oa_403_surfaces_status(self, monkeypatch):
        self._mock_client(monkeypatch, _ProbeResp(403, "text/html"))
        with pytest.raises(_HttpStatusError) as exc:
            _http_download_with_cookie("10.3390/ma16010001", "mdpi",
                                       {}, {"institution": {}})
        assert exc.value.status == 403

    def test_login_redirect_invalidates_cookie(self, monkeypatch):
        invalidated = {"n": 0}
        monkeypatch.setattr(plugin_module, "_invalidate_cookie",
                            lambda c: invalidated.__setitem__("n", invalidated["n"] + 1))
        hop = type("H", (), {"headers": {"location": "https://sso.example/login"}})()
        self._mock_client(monkeypatch, _ProbeResp(302, "text/html", history=[hop]))
        assert _http_download_with_cookie("10.1016/j.body.2023.1", "elsevier",
                                          {}, {"institution": {}}) is None
        assert invalidated["n"] == 1
