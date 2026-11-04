"""下载主流程集成测试（v0.9.0：stub 各层，验证两层接线、降级契约与并发配额）。

v0.9.0 架构：plan 仅剩 oa_direct + api 两层；机构 Cookie 登录通道已移除
（宿主无交互浏览器/登录会话能力）。本文件不得再引用已删除的直连/浏览器符号，
引用即红——这是应用层边界反直连守卫的一部分。
"""

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module


# v0.9.0 已删除的直连/浏览器符号：任何测试不得重新引入（反向守卫）
_REMOVED_SYMBOLS = (
    "_http_download_with_cookie", "_browser_download", "_browser_attempt",
    "_browser_capture_pdf", "_run_browser_attempt_isolated", "_BROWSER_CHILD_CODE",
    "_kill_process_tree", "_STEALTH_INIT_SCRIPT", "_merge_headed_cookies",
    "_BROWSER_OUTCOME", "_client_stream", "_fetch_pdf_direct", "_HTTP_CLIENT",
    "_RETIRED_HTTP_CLIENTS", "_get_http_client", "_close_http_clients", "httpx",
    "_stream_pdf", "_browser_channel_upgrade",
)


def test_removed_direct_symbols_absent():
    """反向守卫：v0.9.0 直连/浏览器层符号必须全部不存在。"""
    for name in _REMOVED_SYMBOLS:
        assert not hasattr(plugin_module, name), f"直连/浏览器残留符号 {name}"


class TestProcessFlow:
    def test_layer1_oa_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plugin_module, "_try_oa_direct",
                            lambda doi, pub, is_oa: "https://x.test/paper.pdf")
        monkeypatch.setattr(plugin_module, "_download_with_retry",
                            lambda *a, **k: (b"%PDF-1.4\n%%EOF\nx", "ok"))
        monkeypatch.setattr(plugin_module, "_validate_pdf", lambda p: True)
        monkeypatch.setattr(plugin_module, "_extract_pdf_meta",
                            lambda p: {"validation_level": "full", "extracted_doi": "10.3390/test"})
        monkeypatch.setattr(plugin_module, "_host_save_pdf",
                            lambda name, data, maximum_bytes=None: {"artifact_id": "a1", "sha256": "d" * 64})
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

    def test_institutional_login_degrades_without_login_window(self, tmp_path, monkeypatch):
        """v0.9.0 契约：机构登录明确降级——_login_and_capture_cookie 恒 None，
        且必须留下 institutional_login_unsupported 证据（不静默失败）。"""
        logged = []
        monkeypatch.setattr(plugin_module, "_log",
                            lambda event, **kw: logged.append((event, kw)))
        assert plugin_module._login_and_capture_cookie({"level": 3}) is None
        assert any(e == "institutional_login_unsupported" for e, _ in logged)
        # Cookie 采集/保存路径同样降级
        assert plugin_module._get_cached_cookie({"level": 3}) is None
        plugin_module._save_cookie({"level": 3}, [{"name": "sid", "value": "x"}])

    def test_artifact_delivery_required(self, tmp_path, monkeypatch):
        """宿主 artifact 不可用时不得计入成功（假成功防护）。"""
        monkeypatch.setattr(plugin_module, "_try_oa_direct",
                            lambda doi, pub, is_oa: "https://x.test/paper.pdf")
        monkeypatch.setattr(plugin_module, "_download_with_retry",
                            lambda *a, **k: (b"%PDF-1.4\n%%EOF\nx", "ok"))
        monkeypatch.setattr(plugin_module, "_validate_pdf", lambda p: True)
        monkeypatch.setattr(plugin_module, "_extract_pdf_meta",
                            lambda p: {"validation_level": "full", "extracted_doi": "10.3390/test"})
        # 宿主 artifact.stream 不可用（降级路径）
        monkeypatch.setattr(plugin_module, "_host_save_pdf", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_mark_done", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)

        paper = {"doi": "10.3390/test", "title": "T", "first_author": "A",
                 "year": "2025", "publisher": "mdpi", "is_oa": True}
        res = plugin_module._process_download(paper, {"level": 1}, Path(tmp_path), {"done": 0, "total": 1})
        assert res["records"] == []
        assert res["errors"][0]["error_class"] == "pdf_invalid"

    def test_process_releases_concurrency_slot(self, tmp_path, monkeypatch):
        """_process 结束后 active 归零（并发配额正确释放）。"""
        monkeypatch.setattr(plugin_module, "_process_download",
                            lambda *a, **k: {"records": [], "errors": [], "progress": {}})
        paper = {"doi": "10.3390/x", "publisher": "mdpi", "is_oa": True}
        res = plugin_module._process({"paper": paper, "config": {"level": 1}, "workspace": str(tmp_path),
                                      "progress": {"done": 0, "total": 1}})
        assert res == {"records": [], "errors": [], "progress": {}}
        assert plugin_module._concurrency_controller.active == 0

    def test_plan_has_no_institutional_layers(self):
        """反向守卫：v0.9.0 通道计划不得包含机构 HTTP/浏览器层。"""
        src = Path(plugin_module.__file__).read_text(encoding="utf-8")
        assert '"institutional_http"' not in src
        assert '"institutional_browser"' not in src

    def test_process_isolates_internal_crash(self, tmp_path, monkeypatch):
        """_process_download 内部抛异常时：不拖垮批次，返回失败记录并释放锁。"""
        def explode(paper, config, workspace, progress):
            raise RuntimeError("boom")

        monkeypatch.setattr(plugin_module, "_process_download", explode)
        monkeypatch.setattr(plugin_module, "_DistributedLock",
                            lambda cfg, workspace=None: type("L", (), {"acquire": lambda s, d: True, "release": lambda s, d: None})())

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
        monkeypatch.setattr(plugin_module, "_DistributedLock", lambda cfg, workspace=None: FakeLock())

        for _ in range(2):
            res = plugin_module._process(
                {"paper": {"doi": "10.1007/x"}, "config": {"level": 1},
                 "workspace": str(tmp_path), "progress": {"done": 0, "total": 1}})
            assert res["errors"] == []
        assert calls["n"] == 2
        assert release_calls["n"] == 2
