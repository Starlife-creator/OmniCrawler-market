"""v0.6.2 测试：view.progress 上报（U6）与面板 text 组件接入。"""

import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module


class _FakeSdk:
    calls: list = []

    @classmethod
    def call(cls, operation, payload):
        cls.calls.append((operation, payload))
        return {"value": None}


class TestViewProgressEmission:
    def test_progress_reported_per_paper(self, tmp_path, monkeypatch):
        """U6：每篇论文结束时上报 view.progress，字段与 broker 白名单一致。"""
        _FakeSdk.calls = []
        plugin_module._RUN_STATS.update({"success": 0, "failed": 0})  # 模块级计数器隔离
        monkeypatch.setitem(sys.modules, "omnicrawler_sdk", _FakeSdk)
        monkeypatch.setattr(plugin_module, "_try_oa_direct",
                            lambda doi, pub, is_oa: "https://x.test/paper.pdf")
        monkeypatch.setattr(plugin_module, "_download_with_retry",
                            lambda *a, **k: (b"%PDF-1.4\nfake", "ok"))
        monkeypatch.setattr(plugin_module, "_validate_pdf", lambda p: True)
        monkeypatch.setattr(plugin_module, "_mark_done", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)

        paper = {"doi": "10.3390/progress", "title": "P", "first_author": "A",
                 "year": "2025", "publisher": "mdpi", "is_oa": True}
        res = plugin_module._process_download(paper, {"level": 1}, Path(tmp_path),
                                              {"done": 2, "total": 5})
        assert res["records"]
        ops = [c for c in _FakeSdk.calls if c[0] == "view.progress"]
        assert len(ops) == 1
        payload = ops[0][1]
        assert set(payload) == {"done", "total", "current_doi",
                                "eta_seconds", "success", "failed"}
        assert payload["done"] == 3 and payload["total"] == 5
        assert payload["current_doi"] == "10.3390/progress"
        assert payload["success"] == 1 and payload["failed"] == 0

    def test_progress_reported_on_failure_too(self, tmp_path, monkeypatch):
        _FakeSdk.calls = []
        plugin_module._RUN_STATS.update({"success": 0, "failed": 0})  # 模块级计数器隔离
        monkeypatch.setitem(sys.modules, "omnicrawler_sdk", _FakeSdk)
        monkeypatch.setattr(plugin_module, "_try_oa_direct", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_check_robots_txt", lambda d: True)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)
        paper = {"doi": "10.9999/fail", "title": "F", "publisher": "unknown", "is_oa": False}
        res = plugin_module._process_download(paper, {"level": 1}, Path(tmp_path),
                                              {"done": 0, "total": 2})
        assert res["records"] == []
        ops = [c for c in _FakeSdk.calls if c[0] == "view.progress"]
        assert len(ops) == 1 and ops[0][1]["failed"] == 1

    def test_seed_resets_counters(self, tmp_path, monkeypatch):
        plugin_module._RUN_STATS.update({"success": 9, "failed": 9})
        xlsx = tmp_path / "wos.xlsx"
        wb = __import__("openpyxl").Workbook()
        ws = wb.active
        ws.append(["DOI"])
        ws.append(["10.9999/one"])
        wb.save(xlsx)
        monkeypatch.setattr(plugin_module, "_batch_check_oa_sync", lambda dois: {})
        res = plugin_module._seed({"file_path": str(xlsx), "workspace": str(tmp_path),
                                   "config": {"level": 1, "dry_run": True}})
        assert res["meta"]["total_papers"] == 1
        assert plugin_module._RUN_STATS == {"success": 0, "failed": 0}

    def test_silent_without_sdk(self, tmp_path, monkeypatch):
        """独立运行（无宿主 SDK）：上报静默 no-op，绝不抛错。"""
        monkeypatch.setitem(sys.modules, "omnicrawler_sdk", None)
        plugin_module._report_view_progress(1, 2, "10.1/x", 1.0, 1, 0)  # 不应抛异常
