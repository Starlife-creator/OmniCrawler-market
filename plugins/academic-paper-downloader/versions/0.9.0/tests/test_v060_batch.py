"""v0.9.0 批处理收尾测试：黄金样本、大批量解析、域画像、无效重试设防、状态版本、降级契约。

浏览器/子进程/直连相关测试（TestBrowserOutcomePropagation / TestBrowserBudgetSelection /
TestProcessIsolation / TestRealChromeChannel / TestPageBlockReason 等）随 v0.9.0 浏览器
实现整体移除而删除；机构层明确降级后，域画像的"跳过 http 直接走浏览器升级"行为不再
存在（plan 仅 oa_direct+api 两层），相关用例已改写。
"""

import json
import sys
import time
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


def _make_wos(path: Path, n: int, with_doi: bool = True) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Publication Type", "Authors", "Article Title", "Publication Year", "DOI"])
    for i in range(n):
        ws.append(["J", f"Author {i}; Other", f"Title {i}", "2025",
                   f"10.9999/paper{i}" if with_doi else ""])
    wb.save(path)


class TestGoldenSeed:
    def test_dry_run_plan_golden_keys(self, tmp_path):
        xlsx = tmp_path / "wos.xlsx"
        _make_wos(xlsx, 3)
        res = plugin_module._seed({"file_path": str(xlsx), "workspace": str(tmp_path),
                                   "config": {"level": 1, "dry_run": True}})
        assert res["errors"] == []
        meta = res["meta"]
        assert set(meta) == {"total_rows", "total_papers", "no_doi_rows",
                             "oa_precheck", "dry_run", "plan"}
        assert meta["total_rows"] == 3 and meta["total_papers"] == 3 and meta["no_doi_rows"] == 0
        assert [p["doi"] for p in meta["plan"]] == [f"10.9999/paper{i}" for i in range(3)]
        for p in meta["plan"]:
            assert set(p) == {"doi", "title", "publisher", "is_oa"}


class TestGoldensReport:
    def test_report_csv_columns_golden(self, tmp_path):
        plugin_module._generate_report(
            tmp_path,
            [{"doi": "10.1/a", "title": "T", "authors": "A", "year": "2025", "journal": "J",
              "publisher": "p", "download_source": "api", "local_path": "papers/a.pdf",
              "file_size": 123, "verified": True}],
            [{"doi": "10.1/b", "title": "B", "layer": "none", "error_class": "network",
              "reason": "网络不可达或请求超时", "time": 0.0}])
        csv_text = next((tmp_path / "reports").glob("download_report_*.csv")).read_text(encoding="utf-8-sig")
        header = csv_text.splitlines()[0]
        assert header == ("DOI,Title,Authors,Year,Journal,Publisher,"
                          "Source,LocalPath,FileSize,Status,Message")
        assert "FAILED" in csv_text and "network@none" in csv_text


class TestLargeBatchParse:
    def test_seed_parses_300_rows_quickly(self, tmp_path):
        xlsx = tmp_path / "wos300.xlsx"
        _make_wos(xlsx, 300)
        t0 = time.time()
        res = plugin_module._seed({"file_path": str(xlsx), "workspace": str(tmp_path),
                                   "config": {"level": 1, "dry_run": True}})
        elapsed = time.time() - t0
        assert res["meta"]["total_rows"] == 300
        assert elapsed < 30, f"解析 300 行耗时 {elapsed:.1f}s，超出预期"


class TestDomainProfile:
    def test_mismatch_marks_and_cooldown_skips_http(self, tmp_path, monkeypatch):
        domain = plugin_module._publisher_domain("mdpi")
        assert domain == "www.mdpi.com"
        plugin_module._profile_channel_mismatch(domain)
        assert plugin_module._domain_http_blocked(domain) is True

        # v0.9.0：浏览器升级通道已移除（plan 仅 oa_direct+api）。域画像生效时
        # oa_direct 门控被跳过，剩余层（api）仍执行；这里用 api 成功证明编排不炸。
        def _fail(*a, **k):
            raise AssertionError("域画像生效时不应尝试 oa_direct")
        monkeypatch.setattr(plugin_module, "_try_oa_direct", _fail)
        monkeypatch.setattr(plugin_module, "_check_robots_txt", lambda d: True)
        monkeypatch.setattr(plugin_module, "_get_cookie_monitor",
                            lambda cfg: type("M", (), {"refresh_if_needed": lambda self: None})())
        monkeypatch.setattr(plugin_module, "_try_api_probe",
                            lambda *a, **k: "https://api.test/x.pdf")
        monkeypatch.setattr(plugin_module, "_download_with_retry",
                            lambda *a, **k: (b"%PDF-1.4\nfake", "ok"))
        monkeypatch.setattr(plugin_module, "_validate_pdf", lambda p: True)
        monkeypatch.setattr(plugin_module, "_extract_pdf_meta",
                            lambda p: {"extracted_doi": "10.3390/profiled"})
        monkeypatch.setattr(plugin_module, "_host_save_pdf",
                            lambda name, data, maximum_bytes=None: {
                                "artifact_id": "sha256:" + "0" * 64, "name": name,
                                "media_type": "application/pdf", "size": len(data),
                                "sha256": "0" * 64})
        monkeypatch.setattr(plugin_module, "_mark_done", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)
        paper = {"doi": "10.3390/profiled", "title": "P", "publisher": "mdpi", "is_oa": True}
        res = plugin_module._process_download(paper, {"level": 2}, Path(tmp_path), {"done": 0, "total": 1})
        assert res["records"], "域画像生效时 oa_direct 被跳过、api 层成功"
        plugin_module._profile_channel_clear(domain)

    def test_clear_removes_block(self):
        plugin_module._profile_channel_mismatch("clear.test")
        assert plugin_module._domain_http_blocked("clear.test") is True
        plugin_module._profile_channel_clear("clear.test")
        assert plugin_module._domain_http_blocked("clear.test") is False


class TestRetryGuardAndClassification:
    def test_no_retry_for_channel_mismatch(self):
        assert plugin_module._retry_strategy("bot_blocked", 0, {}) is None
        assert plugin_module._retry_strategy("captcha", 0, {}) is None
        assert plugin_module._retry_strategy("network", 0, {"retry_count": 3}) is not None

    def test_unknown_publisher_classified(self, tmp_path, monkeypatch):
        monkeypatch.setattr(plugin_module, "_try_oa_direct", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_check_robots_txt", lambda d: True)
        monkeypatch.setattr(plugin_module, "_get_cookie_monitor",
                            lambda cfg: type("M", (), {"refresh_if_needed": lambda self: None})())
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)
        paper = {"doi": "10.9999/unknown-pub", "title": "U", "publisher": "unknown", "is_oa": False}
        res = plugin_module._process_download(paper, {"level": 1}, Path(tmp_path), {"done": 0, "total": 1})
        assert res["errors"][0]["error_class"] == "unknown_publisher"

    def test_failed_record_has_retryable_flag(self, tmp_path):
        plugin_module._set_state_dir(tmp_path)
        try:
            config = {"institution": {}}
            plugin_module._mark_failed(config, "10.1000/r", "none", "network", title="R")
            raw = plugin_module._state_get(plugin_module._failed_key(config))
            rec = json.loads(raw["value"])[0]
            assert rec["retryable"] is True
            plugin_module._mark_failed(config, "10.1000/b", "none", "bot_blocked", title="B")
            raw = plugin_module._state_get(plugin_module._failed_key(config))
            recs = json.loads(raw["value"])
            assert [r["retryable"] for r in recs] == [True, False]
        finally:
            plugin_module._set_state_dir(Path("."))


class TestStateVersionWrapper:
    def test_state_file_has_version(self, tmp_path):
        plugin_module._set_state_dir(tmp_path)
        try:
            config = {"institution": {}}
            plugin_module._mark_done(config, "10.1000/v")
            key = plugin_module._done_key(config)
            f = plugin_module._state_file(key)
            data = json.loads(f.read_text(encoding="utf-8"))
            assert data["v"] == 1 and json.loads(data["value"]) == ["10.1000/v"]
            records, done = plugin_module._load_done_records(config)
            assert done == ["10.1000/v"]
        finally:
            plugin_module._set_state_dir(Path("."))

    def test_legacy_plain_value_still_readable(self, tmp_path):
        plugin_module._set_state_dir(tmp_path)
        try:
            config = {"institution": {}}
            f = plugin_module._state_file(plugin_module._done_key(config))
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(["10.1000/legacy"]), encoding="utf-8")  # 旧格式：裸值
            records, done = plugin_module._load_done_records(config)
            assert done == ["10.1000/legacy"]
        finally:
            plugin_module._set_state_dir(Path("."))


class TestDeferredHeadedTargets:
    def test_headed_pass_degraded_no_retry(self, tmp_path, monkeypatch):
        """v0.9.0：有头轮已明确降级——不调用 _rerun_failed，headed_saved=0，仅记降级日志。"""
        plugin_module._set_state_dir(tmp_path)
        try:
            called = {"n": 0}

            def fake_rerun(*a, **k):
                called["n"] += 1
                return [], []

            monkeypatch.setattr(plugin_module, "_rerun_failed", fake_rerun)
            monkeypatch.setattr(plugin_module, "_generate_report", lambda *a, **k: None)
            monkeypatch.setattr(plugin_module, "_view_sync_from_run", lambda *a, **k: None)
            # 瞬时重试层也会调 _rerun_failed——用 retryable=False 的失败隔离 headed 层
            failed = [
                {"doi": "10.1/bot", "error_class": "bot_blocked", "title": "B", "retryable": False},
                {"doi": "10.1/auth", "error_class": "auth_required", "title": "A", "retryable": False},
            ]
            out = plugin_module._after_run({"workspace": str(tmp_path),
                                            "config": {"defer_headed": True, "retry_prompt_proxy": False},
                                            "results": [], "failed": failed})
            assert called["n"] == 0, "v0.9.0 有头轮降级后不应触发任何重试"
            assert out["headed_saved"] == 0
        finally:
            plugin_module._set_state_dir(Path("."))


class TestProcessIsolation:
    def test_transient_retry_pass_consumes_retryable(self, tmp_path, monkeypatch):
        """retryable 字段的消费端：只有 retryable=true 的失败进瞬时重试轮。"""
        captured = {}

        def fake_rerun(cfg, ws, results, failed, fp, runner, label):
            captured["failed"] = list(failed)
            return [], []

        monkeypatch.setattr(plugin_module, "_rerun_failed", fake_rerun)
        failed = [
            {"doi": "10.1/net", "error_class": "network", "retryable": True},
            {"doi": "10.1/bot", "error_class": "bot_blocked", "retryable": False},
            {"doi": "10.1/noattr", "error_class": "network"},  # 无字段（旧数据）
        ]
        plugin_module._retry_transient_pass(
            {"defer_headed": False}, tmp_path, [], failed, "")
        assert [f["doi"] for f in captured["failed"]] == ["10.1/net"]


class TestApplyRuntimeTuning:
    def test_tuning_applies_and_is_single_entry(self):
        old = plugin_module._MAX_PDF_BYTES
        plugin_module._apply_runtime_tuning({"max_pdf_bytes": 12345})
        assert plugin_module._MAX_PDF_BYTES == 12345
        plugin_module._apply_runtime_tuning({})
        assert plugin_module._MAX_PDF_BYTES == 12345  # 不显式提供则保持
        plugin_module._apply_runtime_tuning({"max_pdf_bytes": old})


class TestBrowserRemovedV090:
    """v0.9.0 反向断言：浏览器/子进程实现已移除（详见 test_layer_institutional.py）。"""

    @pytest.mark.parametrize("name", [
        "_browser_download", "_browser_attempt", "_browser_capture_pdf",
        "_browser_launch_chromium", "_run_browser_attempt_isolated",
        "_page_block_reason", "_BROWSER_OUTCOME", "_BROWSER_CHILD_CODE",
    ])
    def test_removed(self, name):
        assert not hasattr(plugin_module, name)
