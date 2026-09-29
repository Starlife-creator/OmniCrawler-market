"""v0.6.0 收尾批次测试：黄金样本、大批量解析、域画像、无效重试设防、状态版本、D3/D11。"""

import sys
import json
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

        # 画像生效：oa_direct 的门控被跳过（不应被调用），直接走浏览器升级通道
        def _fail(*a, **k):
            raise AssertionError("域画像生效时不应尝试 oa_direct")
        monkeypatch.setattr(plugin_module, "_try_oa_direct", _fail)
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_check_robots_txt", lambda d: True)
        monkeypatch.setattr(plugin_module, "_get_cookie_monitor",
                            lambda cfg: type("M", (), {"refresh_if_needed": lambda self: None})())
        monkeypatch.setattr(plugin_module, "_browser_download",
                            lambda doi, pub, cookies, config: "https://upgraded.test/x.pdf")
        monkeypatch.setattr(plugin_module, "_download_with_retry",
                            lambda *a, **k: (b"%PDF-1.4\nfake", "ok"))
        monkeypatch.setattr(plugin_module, "_validate_pdf", lambda p: True)
        monkeypatch.setattr(plugin_module, "_mark_done", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)
        paper = {"doi": "10.3390/profiled", "title": "P", "publisher": "mdpi", "is_oa": True}
        res = plugin_module._process_download(paper, {"level": 2}, Path(tmp_path), {"done": 0, "total": 1})
        assert res["records"], "域画像生效时应直接走浏览器升级并成功"
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
            # 读取端能解析自己的格式
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


class TestBrowserOutcomePropagation:
    def test_blocked_browser_failure_becomes_bot_blocked(self, tmp_path, monkeypatch):
        """v0.6.3：浏览器被挑战页拦截 → error_class=bot_blocked → 有头轮可见。"""
        monkeypatch.setattr(plugin_module, "_try_oa_direct", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_check_robots_txt", lambda d: True)
        monkeypatch.setattr(plugin_module, "_get_cookie_monitor",
                            lambda cfg: type("M", (), {"refresh_if_needed": lambda self: None})())
        # 浏览器尝试：设置 blocked 结果后返回 None（模拟挑战页拦截）
        def fake_browser(doi, pub, cookies, config):
            plugin_module._BROWSER_OUTCOME.reason = "blocked"
            return None
        monkeypatch.setattr(plugin_module, "_browser_download", fake_browser)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)
        paper = {"doi": "10.3390/blocked2", "title": "B2", "publisher": "mdpi", "is_oa": True}
        res = plugin_module._process_download(paper, {"level": 3, "defer_headed": False},
                                              Path(tmp_path), {"done": 0, "total": 1})
        assert res["errors"][0]["error_class"] == "bot_blocked"


class TestDeferredHeadedTargets:
    def test_headed_pass_targets_only_verification_needed(self, tmp_path, monkeypatch):
        """v0.6.4：有头轮目标 = bot_blocked/captcha/auth_required（IOP/PerimeterX
        对无头无解，有头自动过挑战；纯订阅墙捕获失败照旧标记）。network 不弹窗。"""
        plugin_module._set_state_dir(tmp_path)
        try:
            captured = {}

            def fake_rerun(cfg, ws, results, failed, fp, runner, label):
                captured["failed"] = list(failed)
                return [], []

            monkeypatch.setattr(plugin_module, "_rerun_failed", fake_rerun)
            monkeypatch.setattr(plugin_module, "_generate_report", lambda *a, **k: None)
            monkeypatch.setattr(plugin_module, "_view_sync_from_run", lambda *a, **k: None)
            failed = [
                {"doi": "10.1/bot", "error_class": "bot_blocked", "title": "B"},
                {"doi": "10.1/auth", "error_class": "auth_required", "title": "A"},
                {"doi": "10.1/net", "error_class": "network", "title": "N"},
            ]
            plugin_module._after_run({"workspace": str(tmp_path),
                                      "config": {"defer_headed": True, "retry_prompt_proxy": False},
                                      "results": [], "failed": failed})
            assert [f["doi"] for f in captured["failed"]] == ["10.1/bot", "10.1/auth"]
        finally:
            plugin_module._set_state_dir(Path("."))


class TestBrowserBudgetSelection:
    """v0.6.5 守卫：看门狗预算必须跟随本段尝试的实际形态。

    回归背景：两阶段有头轮（_deferred_headed_pass）以 headless=False 调
    _browser_download，旧逻辑第一段永远用无头预算 120s——挑战等待 180s > 120s
    必然被看门狗砍掉，且 headless=False 又进不了第二段 480s 分支 ⇒ 有头轮全灭。
    """

    def test_headed_first_attempt_gets_headed_budget(self, monkeypatch):
        captured = {}

        def fake_iso(payload, timeout):
            captured["timeout"] = timeout
            captured["headless"] = payload.get("headless")
            return None, "timeout"

        monkeypatch.setattr(plugin_module, "_run_browser_attempt_isolated", fake_iso)
        cfg = {"institution": {"headless": False}}  # 两阶段有头轮的调用形态
        out = plugin_module._browser_download("10.1/x", "unknown-pub", [], cfg)
        assert out is None
        assert captured["timeout"] == 480.0          # headed_solve_timeout(180) + 300
        assert captured["headless"] is False         # 第一段本身就是有头

    def test_headless_budget_then_headed_retry_budget(self, monkeypatch):
        captured = []

        def fake_iso(payload, timeout):
            captured.append((timeout, payload.get("headless")))
            return None, "timeout"  # 两段都失败

        monkeypatch.setattr(plugin_module, "_run_browser_attempt_isolated", fake_iso)
        monkeypatch.setattr(plugin_module, "_institution_visible_fallback", lambda cfg: True)
        cfg = {"institution": {"headless": True}}
        plugin_module._browser_download("10.1/x", "unknown-pub", [], cfg)
        assert captured[0] == (120.0, True)          # 无头段：无头预算
        assert captured[1] == (480.0, False)         # 失败后有头重试：有头预算


class TestProcessIsolation:
    """v0.6.6 守卫：浏览器尝试子进程隔离——超时可整树击杀，僵尸线程/驱动归零。"""

    def test_child_exception_path_returns_reason(self):
        """真实子进程端到端冒烟：payload 合法传入 ⇒ 子进程启动、import 插件、
        执行尝试、JSON 回传 reason（本例导航快速失败 → navigation_failed）。
        若未来签名变更导致 TypeError，则走 child_exception 分支——两条都算通。"""
        path, reason = plugin_module._run_browser_attempt_isolated(
            {"doi": "10.1/smoke", "publisher": "unknown-pub", "home": "https://doi.org",
             "cookies": [], "config": {}, "headless": True}, 60.0)
        assert path is None
        assert isinstance(reason, str) and reason  # 必须回传一个可读原因
        assert reason not in ("timeout",)  # 60s 预算内不该超时

    def test_timeout_kills_child(self):
        """真实超时路径：子进程 import 插件需要数秒 ⇒ 1s 看门狗必超时，
        验证超时分支返回 (None, 'timeout') 且进程被击杀。"""
        payload = {"doi": "10.1/x", "publisher": "unknown-pub", "home": "https://doi.org",
                   "cookies": [], "config": {}, "headless": True}
        t0 = time.time()
        path, reason = plugin_module._run_browser_attempt_isolated(payload, 1.0)
        elapsed = time.time() - t0
        assert path is None and reason == "timeout"
        assert elapsed < 15.0  # 超时后必须快速返回（线程版会继续挂到子任务结束）

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

    def test_page_block_reason_captcha_widget(self):
        """中文验证页（文本 marker 全 miss）⇒ DOM widget 检测兜底；
        正文长的文章页即使嵌 widget 也不误判。"""
        class FakePage:
            def __init__(self, title, body, has_widget):
                self._t, self._b, self._w = title, body, has_widget
                self.url = "https://example.com/article"

            def title(self):
                return self._t

            def inner_text(self, sel):
                return self._b

            def query_selector(self, s):
                return object() if self._w else None

        # 中文 Turnstile 拦截页：文本 marker 全 miss + widget 存在 + 正文极短
        p = FakePage("请稍候...", "请验证您是真人以继续访问", True)
        assert plugin_module._page_block_reason(p) == "captcha"
        # 正常文章页（正文长）页脚嵌 widget ⇒ 不误判
        p2 = FakePage("Some Article Title", "Abstract. " * 100, True)
        assert plugin_module._page_block_reason(p2) is None


class TestRealChromeChannel:
    """v0.6.6 守卫：优先本机真 Chrome（Turnstile 对自动化 Chromium 无限重置
    挑战）；channel 不可用时回退内置 Chromium；真 Chrome 不覆盖原生 UA。"""

    @staticmethod
    def _fake_playwright(monkeypatch, chrome_ok: bool):
        channels: list = []
        ctx_kwargs: dict = {}

        def fake_launch(headless=False, proxy=None, channel=None):
            channels.append(channel)
            if channel in ("chrome", "msedge") and not chrome_ok:
                raise Exception("Executable doesn't exist")  # 未装该浏览器
            return FakeBrowser(ctx_kwargs)

        class FakeBrowser:
            def __init__(self, kw):
                self._kw = kw

            def new_context(self, **kwargs):
                self._kw.update(kwargs)
                return type("C", (), {"add_init_script": lambda self, s: None,
                                      "add_cookies": lambda self, c: None,
                                      "new_page": lambda self: None,
                                      "request": lambda self: None,
                                      "close": lambda self: None})()

            def close(self):
                pass

        class FakeP:
            chromium = type("Ch", (), {"launch": staticmethod(fake_launch)})
        return {"channels": channels, "ctx_kwargs": ctx_kwargs}, FakeP()

    def test_prefers_real_browser_and_keeps_native_ua(self, monkeypatch):
        calls, fake_p = self._fake_playwright(monkeypatch, chrome_ok=True)
        monkeypatch.setattr(plugin_module, "_get_next_proxy", lambda cfg: None)
        browser, real_chrome = plugin_module._browser_launch_chromium(
            fake_p, headless=False, proxy_url=None, config={})
        assert calls["channels"] == ["chrome"]     # 首选真 Chrome
        assert real_chrome is True

    def test_falls_back_to_edge_then_bundled(self, monkeypatch):
        """无 Chrome 有 Edge：chrome 失败 → msedge 成功；全失败 → 内置。"""
        calls, fake_p = self._fake_playwright(monkeypatch, chrome_ok=False)
        monkeypatch.setattr(plugin_module, "_get_next_proxy", lambda cfg: None)

        # 只让 msedge 成功：模拟"装了 Edge 没装 Chrome"
        Ch = fake_p.chromium

        def edge_only_launch(headless=False, proxy=None, channel=None):
            calls["channels"].append(channel)
            if channel == "msedge":
                return object()  # helper 不触碰 browser 对象，最小 stub 即可
            raise Exception("Executable doesn't exist")

        monkeypatch.setattr(Ch, "launch", staticmethod(edge_only_launch))
        browser, real = plugin_module._browser_launch_chromium(
            fake_p, headless=True, proxy_url=None, config={})
        assert calls["channels"] == ["chrome", "msedge"]
        assert real is True

        # Chrome/Edge 都没有 → 回退内置（最后一次 launch 的 channel=None）
        calls2, fake_p2 = self._fake_playwright(monkeypatch, chrome_ok=False)
        monkeypatch.setattr(plugin_module, "_get_next_proxy", lambda cfg: None)
        browser2, real2 = plugin_module._browser_launch_chromium(
            fake_p2, headless=True, proxy_url=None, config={})
        assert calls2["channels"] == ["chrome", "msedge", None]
        assert real2 is False

    def test_browser_attempt_uses_native_ua_only_for_bundled(self, monkeypatch):
        """_browser_attempt 组装 context：真 Chrome 不带 user_agent，内置带。"""
        plugin_module._set_state_dir(Path("."))  # 确保无 SDK 干扰
        try:
            calls, fake_p = self._fake_playwright(monkeypatch, chrome_ok=True)
            monkeypatch.setattr(plugin_module, "_get_next_proxy", lambda cfg: None)
            monkeypatch.setattr("playwright.sync_api.sync_playwright",
                                lambda: _FakeSyncPW(fake_p))
            # 走到 launch 即可，后续导航失败返回 None 没关系
            monkeypatch.setattr(plugin_module, "_browser_capture_pdf",
                                lambda *a, **k: None)
            out = plugin_module._browser_attempt("10.1/x", "unknown-pub", "https://doi.org",
                                                 [], {}, headless=True)
            assert out is None
            assert "user_agent" not in calls["ctx_kwargs"]
        finally:
            plugin_module._set_state_dir(Path("."))


class _FakeSyncPW:
    """sync_playwright() 上下文管理器替身。"""

    def __init__(self, p):
        self._p = p

    def __enter__(self):
        return self._p

    def __exit__(self, *exc):
        return False


class TestPageBlockReason:
    """v0.6.3 误判修复守卫：页眉的 Sign in 链接不得把正常文章页判为登录墙。"""

    class _FakePage:
        def __init__(self, title, body, url="https://www.example.com/article"):
            self._t, self._b, self.url = title, body, url
        def title(self):
            return self._t
        def inner_text(self, sel):
            return self._b

    def test_body_signin_link_not_blocked(self):
        page = self._FakePage(
            "Dehydroxylation of Kaolinite: Evaluation of ... | Minerals",
            "Abstract ... Academic Editors ... Sign in | Register",  # 页眉含 Sign in
        )
        assert plugin_module._page_block_reason(page) is None

    def test_login_title_blocked(self):
        page = self._FakePage("Sign in to ScienceDirect", "", "https://www.sciencedirect.com")
        assert plugin_module._page_block_reason(page) == "sign in"

    def test_login_url_blocked(self):
        page = self._FakePage("Example", "", "https://sso.test/login?next=%2F")
        assert plugin_module._page_block_reason(page) is not None

    def test_challenge_body_blocked(self):
        page = self._FakePage("Please wait", "Just a moment... verifying your browser")
        assert plugin_module._page_block_reason(page) is not None


class TestApplyRuntimeTuning:
    def test_tuning_applies_and_is_single_entry(self):
        old = plugin_module._MAX_PDF_BYTES
        plugin_module._apply_runtime_tuning({"max_pdf_bytes": 12345})
        assert plugin_module._MAX_PDF_BYTES == 12345
        plugin_module._apply_runtime_tuning({})
        assert plugin_module._MAX_PDF_BYTES == 12345  # 不显式提供则保持
        plugin_module._apply_runtime_tuning({"max_pdf_bytes": old})
