"""下载主流程集成测试（stub 各层，验证三层接线与并发配额）。"""

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module


class TestProcessFlow:
    def test_layer1_oa_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plugin_module, "_try_oa_direct",
                            lambda doi, pub, is_oa: "https://x.test/paper.pdf")
        monkeypatch.setattr(plugin_module, "_download_with_retry",
                            lambda *a, **k: (b"%PDF-1.4\n%%EOF\nx", "ok"))
        monkeypatch.setattr(plugin_module, "_validate_pdf", lambda p: True)
        monkeypatch.setattr(plugin_module, "_mark_done", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)

        paper = {"doi": "10.3390/test", "title": "T", "first_author": "A",
                 "year": "2025", "publisher": "mdpi", "is_oa": True}
        res = plugin_module._process_download(paper, {"level": 1}, Path(tmp_path), {"done": 0, "total": 1})
        assert res["records"] and res["records"][0]["doi"] == "10.3390/test"
        assert (Path(tmp_path) / "papers").exists()

    def test_all_layers_failed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plugin_module, "_try_oa_direct", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_download_with_retry",
                            lambda *a, **k: (None, "unknown"))
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)

        paper = {"doi": "10.9999/never", "title": "N", "publisher": "unknown", "is_oa": False}
        res = plugin_module._process_download(paper, {"level": 1}, Path(tmp_path), {"done": 0, "total": 1})
        assert res["records"] == []
        assert res["errors"][0]["reason"] == "all_layers_failed"

    def test_process_releases_concurrency_slot(self, tmp_path, monkeypatch):
        """_process 结束后 active 归零（并发配额正确释放）。"""
        monkeypatch.setattr(plugin_module, "_process_download",
                            lambda *a, **k: {"records": [], "errors": [], "progress": {}})
        paper = {"doi": "10.3390/x", "publisher": "mdpi", "is_oa": True}
        res = plugin_module._process({"paper": paper, "config": {"level": 1}, "workspace": str(tmp_path),
                                      "progress": {"done": 0, "total": 1}})
        assert res == {"records": [], "errors": [], "progress": {}}
        assert plugin_module._concurrency_controller.active == 0

    def test_layer3_relogin_retry(self, tmp_path, monkeypatch):
        """认证失效 → 重新登录 → 重试成功。"""
        state = {"relogin_done": False}

        def fake_http(doi, publisher, cookies, config):
            return "https://x.test/paper.pdf"

        def fake_download(pdf_url, paper, config, cookies, error_class="unknown", headers=None, **kwargs):
            # 第一次返回认证失败，重登后返回成功
            if not state["relogin_done"]:
                return None, "auth_required"
            return b"%PDF-1.4\n%%EOF\nx", "ok"

        def fake_login(config):
            state["relogin_done"] = True
            return [{"name": "sid", "value": "new"}]

        monkeypatch.setattr(plugin_module, "_try_oa_direct", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_http_download_with_cookie", fake_http)
        monkeypatch.setattr(plugin_module, "_download_with_retry", fake_download)
        monkeypatch.setattr(plugin_module, "_browser_download", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_login_and_capture_cookie", fake_login)
        monkeypatch.setattr(plugin_module, "_validate_pdf", lambda p: True)
        monkeypatch.setattr(plugin_module, "_mark_done", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)

        paper = {"doi": "10.1039/x", "title": "X", "first_author": "A",
                 "year": "2025", "publisher": "rsc", "is_oa": False}
        # 先制造有效 cookie 走 Layer 3
        monkeypatch.setattr(plugin_module, "_get_cookie_monitor",
                            lambda c: type("M", (), {"refresh_if_needed": lambda s: [{"name": "sid", "value": "old"}]})())
        res = plugin_module._process_download(paper, {"level": 3}, Path(tmp_path), {"done": 0, "total": 1})
        assert state["relogin_done"] is True
        assert res["records"] and res["records"][0]["doi"] == "10.1039/x"

    def test_campus_direct_runs_browser_without_cookies(self, tmp_path, monkeypatch):
        """校园直连：无 Cookie 也触发 Layer 3 浏览器下载（IP 即授权）。"""
        calls = {"browser": 0, "http": 0}

        def fake_http(doi, publisher, cookies, config):
            calls["http"] += 1
            return None

        def fake_browser(doi, publisher, cookies, config):
            calls["browser"] += 1
            assert cookies == []  # 校园直连无 cookie
            return "https://x.test/paper.pdf"

        monkeypatch.setattr(plugin_module, "_campus_direct", lambda c: True)
        monkeypatch.setattr(plugin_module, "_get_cookie_monitor",
                            lambda c: type("M", (), {"refresh_if_needed": lambda s: None})())
        monkeypatch.setattr(plugin_module, "_try_oa_direct", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_http_download_with_cookie", fake_http)
        monkeypatch.setattr(plugin_module, "_browser_download", fake_browser)
        monkeypatch.setattr(plugin_module, "_download_with_retry",
                            lambda *a, **k: (b"%PDF-1.4\n%%EOF\nx", "ok"))
        monkeypatch.setattr(plugin_module, "_validate_pdf", lambda p: True)
        monkeypatch.setattr(plugin_module, "_mark_done", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)

        paper = {"doi": "10.1016/j.paper.2023.1", "title": "P", "publisher": "elsevier", "is_oa": False}
        res = plugin_module._process_download(paper, {"level": 3, "campus_ip": True}, Path(tmp_path), {"done": 0, "total": 1})
        assert calls["browser"] >= 1
        assert res["records"][0]["doi"] == "10.1016/j.paper.2023.1"

    def test_relogin_not_triggered_without_prior_cookies(self, tmp_path, monkeypatch):
        """校园直连模式认证失败时不应触发账号重登（本就没有登录态）。"""
        login_calls = {"n": 0}

        def fake_http(doi, publisher, cookies, config):
            return None

        def fake_login(config):
            login_calls["n"] += 1
            return [{"name": "sid", "value": "x"}]

        monkeypatch.setattr(plugin_module, "_campus_direct", lambda c: True)
        monkeypatch.setattr(plugin_module, "_get_cookie_monitor",
                            lambda c: type("M", (), {"refresh_if_needed": lambda s: None})())
        monkeypatch.setattr(plugin_module, "_try_oa_direct", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_http_download_with_cookie", fake_http)
        monkeypatch.setattr(plugin_module, "_browser_download", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_download_with_retry",
                            lambda *a, **k: (None, "auth_required"))
        monkeypatch.setattr(plugin_module, "_login_and_capture_cookie", fake_login)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)

        paper = {"doi": "10.1016/j.elsevier.2023.1", "publisher": "elsevier", "is_oa": False}
        plugin_module._process_download(paper, {"level": 3, "campus_ip": True}, Path(tmp_path), {"done": 0, "total": 1})
        assert login_calls["n"] == 0

    def test_browser_temp_file_cleaned_up(self, tmp_path, monkeypatch):
        """浏览器导出的临时 PDF 读取后应被删除，不留垃圾文件。"""
        tmp_pdf = Path(tmp_path) / "browser_export.pdf"
        tmp_pdf.write_bytes(b"%PDF-1.4\n%%EOF\nx")

        def fake_browser(doi, publisher, cookies, config):
            return str(tmp_pdf)

        monkeypatch.setattr(plugin_module, "_campus_direct", lambda c: True)
        monkeypatch.setattr(plugin_module, "_get_cookie_monitor",
                            lambda c: type("M", (), {"refresh_if_needed": lambda s: None})())
        monkeypatch.setattr(plugin_module, "_try_oa_direct", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_http_download_with_cookie", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_browser_download", fake_browser)
        monkeypatch.setattr(plugin_module, "_validate_pdf", lambda p: True)
        monkeypatch.setattr(plugin_module, "_mark_done", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)

        paper = {"doi": "10.1016/j.campus.2023.1", "title": "P", "first_author": "A",
                 "year": "2025", "publisher": "elsevier", "is_oa": False}
        res = plugin_module._process_download(paper, {"level": 3, "campus_ip": True}, Path(tmp_path), {"done": 0, "total": 1})
        assert res["records"][0]["doi"] == "10.1016/j.campus.2023.1"
        assert tmp_pdf.exists() is False  # 临时文件已清理

    def test_oa_publisher_403_not_relogin(self, tmp_path, monkeypatch):
        """MDQI/RSC 等 OA 源 403（反爬）不应触发机构重登。"""
        login_calls = {"n": 0}

        def fake_http(doi, publisher, cookies, config):
            return "https://www.mdpi.com/10.3390/x/pdf"

        def fake_download(pdf_url, paper, config, cookies, error_class="unknown", headers=None, **kwargs):
            return None, "bot_blocked"

        def fake_login(config):
            login_calls["n"] += 1
            return [{"name": "sid", "value": "x"}]

        monkeypatch.setattr(plugin_module, "_get_cookie_monitor",
                            lambda c: type("M", (), {"refresh_if_needed": lambda s: [{"name": "sid", "value": "old"}]})())
        monkeypatch.setattr(plugin_module, "_try_oa_direct", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_http_download_with_cookie", fake_http)
        monkeypatch.setattr(plugin_module, "_download_with_retry", fake_download)
        monkeypatch.setattr(plugin_module, "_browser_download", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_login_and_capture_cookie", fake_login)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)

        paper = {"doi": "10.3390/x", "publisher": "mdpi", "is_oa": True}
        plugin_module._process_download(paper, {"level": 3}, Path(tmp_path), {"done": 0, "total": 1})
        assert login_calls["n"] == 0

    def test_process_isolates_internal_crash(self, tmp_path, monkeypatch):
        """_process_download 内部抛异常时：不拖垮批次，返回失败记录并释放锁。"""
        def explode(paper, config, workspace, progress):
            raise RuntimeError("boom")

        monkeypatch.setattr(plugin_module, "_process_download", explode)
        monkeypatch.setattr(plugin_module, "_DistributedLock",
                            lambda cfg: type("L", (), {"acquire": lambda s, d: True, "release": lambda s, d: None})())

        res = plugin_module._process(
            {"paper": {"doi": "10.1007/x", "title": "T"}, "config": {"level": 1},
             "workspace": str(tmp_path), "progress": {"done": 0, "total": 3}})
        assert res["errors"][0]["reason"].startswith("internal_error:")

    def test_process_relocks_after_crash(self, tmp_path, monkeypatch):
        """崩溃后分布式锁仍被释放，后续论文可正常获取。"""
        calls = {"n": 0}
        release_calls = {"n": 0}

        def one(paper, config, workspace, progress):
            return {"records": [], "errors": [], "progress": {"done": 1, "total": 1}}

        class FakeLock:
            def acquire(self, doi):
                calls["n"] += 1
                return True

            def release(self, doi):
                release_calls["n"] += 1

        monkeypatch.setattr(plugin_module, "_process_download", one)
        monkeypatch.setattr(plugin_module, "_DistributedLock", lambda cfg: FakeLock())

        for _ in range(2):
            res = plugin_module._process(
                {"paper": {"doi": "10.1007/x"}, "config": {"level": 1},
                 "workspace": str(tmp_path), "progress": {"done": 0, "total": 1}})
            assert res["errors"] == []
        assert calls["n"] == 2
        assert release_calls["n"] == 2