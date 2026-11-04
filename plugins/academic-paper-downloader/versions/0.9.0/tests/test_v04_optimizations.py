"""v0.4.0 优化项测试：robots 缓存、状态文件兜底、镜像优先、代理客户端重建、通道升级。"""

import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module


@pytest.fixture(autouse=True)
def _isolate_domain_profile():
    """域画像是模块级状态：测试间必须隔离，否则跨测试污染会跳过 http 通道。"""
    plugin_module._CHANNEL_PROFILE.clear()
    yield
    plugin_module._CHANNEL_PROFILE.clear()


class TestRobotsCache:
    def test_same_domain_requested_once(self, monkeypatch):
        plugin_module._ROBOTS_CACHE.clear()
        calls = []

        def fake_host_fetch(url, headers=None):
            calls.append(url)
            return (b"User-agent: *\nDisallow: /pdf\n", 200, url)

        monkeypatch.setattr(plugin_module, "_host_fetch", fake_host_fetch)
        assert plugin_module._check_robots_txt("blocked.test") is False
        assert plugin_module._check_robots_txt("blocked.test") is False
        assert len(calls) == 1  # 第二次命中缓存

    def test_cache_per_domain(self, monkeypatch):
        plugin_module._ROBOTS_CACHE.clear()
        monkeypatch.setattr(plugin_module, "_host_fetch",
                            lambda url, headers=None: (b"", 404, url))
        assert plugin_module._check_robots_txt("a.test") is True
        assert plugin_module._check_robots_txt("b.test") is True
        assert "a.test" in plugin_module._ROBOTS_CACHE and "b.test" in plugin_module._ROBOTS_CACHE


class TestStateFileFallback:
    def test_mark_done_roundtrip_without_sdk(self, tmp_path, monkeypatch):
        # 确保 omnicrawler_sdk 不可用（模拟独立运行）
        monkeypatch.setitem(sys.modules, "omnicrawler_sdk", None)
        plugin_module._set_state_dir(tmp_path)
        try:
            config = {"institution": {}}
            plugin_module._mark_done(config, "10.1000/xyz",
                                     {"doi": "10.1000/xyz", "title": "T", "verified": True})
            records, done = plugin_module._load_done_records(config)
            assert done == ["10.1000/xyz"]
            assert records and records[0]["doi"] == "10.1000/xyz"
            assert records[0]["title"] == "T"
            assert (tmp_path / ".apd_state").is_dir()
        finally:
            plugin_module._set_state_dir(Path("."))

    def test_mark_failed_persists(self, tmp_path):
        plugin_module._set_state_dir(tmp_path)
        try:
            config = {"institution": {}}
            plugin_module._mark_failed(config, "10.1000/fail", "none", "bot_blocked", title="X")
            raw = plugin_module._state_get(plugin_module._failed_key(config))
            failed = json.loads(raw["value"])
            assert failed[0]["doi"] == "10.1000/fail"
            assert failed[0]["error_class"] == "bot_blocked"
            assert failed[0]["reason"] == plugin_module._failure_reason("bot_blocked")
        finally:
            plugin_module._set_state_dir(Path("."))

    def test_cookie_never_written_to_file(self, tmp_path):
        """D9 安全回归守卫：Cookie 是会话凭证，禁止明文落入 workspace 文件。"""
        plugin_module._set_state_dir(tmp_path)
        try:
            plugin_module._save_cookie({"institution": {}}, [{"name": "sid", "value": "secret", "expires": -1}])
            cookie_files = list((tmp_path / ".apd_state").glob("apd_cookie_*.json"))
            assert cookie_files == [], "Cookie 不得明文落盘"
        finally:
            plugin_module._set_state_dir(Path("."))

    def test_stale_cookie_files_cleaned_on_state_dir_set(self, tmp_path):
        d = tmp_path / ".apd_state"
        d.mkdir(parents=True)
        stale = d / "apd_cookie_abc123.json"
        stale.write_text("[]", encoding="utf-8")
        plugin_module._set_state_dir(tmp_path)
        assert not stale.exists()


class TestUnpaywallMirrorPreference:
    def test_repository_url_wins_over_publisher(self, monkeypatch):
        payload = json.dumps({
            "best_oa_location": {"host_type": "publisher",
                                 "url_for_pdf": "https://iopscience.iop.org/article/x/pdf"},
            "oa_locations": [
                {"host_type": "publisher", "url_for_pdf": "https://iopscience.iop.org/article/x/pdf"},
                {"host_type": "repository", "url_for_pdf": "https://arxiv.org/pdf/1234.pdf"},
            ],
        }).encode("utf-8")

        def fake_host_fetch(url, headers=None):
            return (payload, 200, url)

        monkeypatch.setattr(plugin_module, "_host_fetch", fake_host_fetch)
        url = plugin_module._try_api_probe("10.1000/mirror", {"unpaywall_email": "t@t.io"})
        assert url == "https://arxiv.org/pdf/1234.pdf"

    def test_falls_back_to_best_location_without_repository(self, monkeypatch):
        payload = json.dumps({
            "best_oa_location": {"host_type": "publisher",
                                 "url_for_pdf": "https://pub.test/x.pdf"},
            "oa_locations": [{"host_type": "publisher", "url_for_pdf": "https://pub.test/x.pdf"}],
        }).encode("utf-8")

        def fake_host_fetch(url, headers=None):
            return (payload, 200, url)

        monkeypatch.setattr(plugin_module, "_host_fetch", fake_host_fetch)
        url = plugin_module._try_api_probe("10.1000/nomirror", {"unpaywall_email": "t@t.io"})
        assert url == "https://pub.test/x.pdf"


class TestHostFetchContract:
    """v0.9.0：所有网络请求必须经宿主 network.fetch，不得自建 HTTP 客户端。"""

    def test_host_fetch_is_used_for_api_probe(self, monkeypatch):
        calls = []

        def fake_host_fetch(url, headers=None):
            calls.append(url)
            return (json.dumps({"message": {"link": [
                {"content-type": "application/pdf", "URL": "https://api.test/x.pdf"}]}}).encode(), 200, url)

        monkeypatch.setattr(plugin_module, "_host_fetch", fake_host_fetch)
        url = plugin_module._try_api_probe("10.1000/crossref", {})
        assert url == "https://api.test/x.pdf"
        assert calls and "api.crossref.org" in calls[0]

    def test_no_direct_http_client_symbols(self):
        """反向守卫：v0.9.0 不得残留任何自建 HTTP 客户端符号。"""
        for name in ("httpx", "_HTTP_CLIENT", "_RETIRED_HTTP_CLIENTS",
                     "_get_http_client", "_close_http_clients", "_client_stream"):
            assert not hasattr(plugin_module, name), f"直连 HTTP 残留符号 {name}"

    def test_host_fetch_missing_sdk_degrades(self, monkeypatch):
        """宿主 SDK 不可用时 _host_fetch 抛错（绝不静默成功/拒绝直连降级）。"""
        monkeypatch.setitem(sys.modules, "omnicrawler_sdk", None)
        with pytest.raises(Exception):
            plugin_module._host_fetch("https://x.test/a.pdf")
