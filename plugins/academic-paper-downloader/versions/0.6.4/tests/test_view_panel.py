"""v0.5.0 view 面板（登录态控制中心）契约测试。"""

import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module


class TestViewDescribe:
    def test_descriptor_shape(self):
        res = plugin_module.handle("view.describe", {})
        view = res["view"]
        assert view["view_id"] == "academic-paper-downloader.main"
        ids = [c["id"] for c in view["components"]]
        assert ids == ["status", "proxy-input", "login-url-input",
                       "open-login", "clear-login", "refresh", "message"]
        texts = {c["id"]: c for c in view["components"] if c["type"] == "text"}
        assert texts["proxy-input"]["action"] == "configure-proxy"
        assert texts["login-url-input"]["action"] == "configure-login-url"
        actions = {c["id"]: c.get("action") for c in view["components"]}
        assert actions["open-login"] == "open-login"
        assert actions["clear-login"] == "clear-login"

    def test_cookie_status_reflects_absence(self, tmp_path):
        plugin_module._set_state_dir(tmp_path)
        try:
            res = plugin_module.handle("view.describe", {})
            status = next(c for c in res["view"]["components"] if c["id"] == "status")
            assert "无登录态" in status["text"]
        finally:
            plugin_module._set_state_dir(Path("."))


class TestViewActions:
    def test_open_login_without_url_is_rejected(self, tmp_path):
        plugin_module._set_state_dir(tmp_path)
        try:
            res = plugin_module.handle("view.action", {"action": "open-login"})
            assert "尚未配置登录页" in res["message"]
        finally:
            plugin_module._set_state_dir(Path("."))

    def test_open_login_rejects_reentry(self, tmp_path, monkeypatch):
        plugin_module._set_state_dir(tmp_path)
        try:
            plugin_module._view_cfg_save({"login_url": "https://login.test", "message": ""})
            # 模拟已有登录线程在跑（Event 保持存活，防竞态）
            import threading
            ev = threading.Event()
            blocker = threading.Thread(target=ev.wait)
            blocker.start()
            monkeypatch.setattr(plugin_module, "_LOGIN_THREAD", blocker, raising=False)
            res = plugin_module.handle("view.action", {"action": "open-login"})
            assert "已在进行中" in res["message"]
            ev.set()
            blocker.join()
        finally:
            plugin_module._set_state_dir(Path("."))

    def test_clear_login_invalidates_and_reports(self, tmp_path):
        plugin_module._set_state_dir(tmp_path)
        try:
            config = {"institution": {}}
            plugin_module._save_cookie(config, [{"name": "sid", "value": "v", "expires": -1}])
            res = plugin_module.handle("view.action", {"action": "clear-login"})
            assert "已清除" in res["message"]
            assert plugin_module._get_cached_cookie(config) is None
        finally:
            plugin_module._set_state_dir(Path("."))

    def test_unknown_action_is_reported(self):
        res = plugin_module.handle("view.action", {"action": "no-such"})
        assert "未知操作" in res["message"]

    def test_choose_proxy_persists(self, tmp_path):
        plugin_module._set_state_dir(tmp_path)
        try:
            res = plugin_module.handle("view.action",
                                       {"action": "choose-proxy",
                                        "payload": {"value": "http://proxy.lib.test:8080"}})
            assert "http://proxy.lib.test:8080" in res["message"]
            assert plugin_module._view_cfg()["proxy_url"] == "http://proxy.lib.test:8080"
        finally:
            plugin_module._set_state_dir(Path("."))

    def test_text_inputs_persist_values(self, tmp_path):
        """U4：面板 text 组件（configure-proxy / configure-login-url）持久化输入值。"""
        plugin_module._set_state_dir(tmp_path)
        try:
            res = plugin_module.handle("view.action",
                                       {"action": "configure-proxy",
                                        "payload": {"value": "http://proxy.lib.test:8080"}})
            assert "proxy.lib.test" in res["message"]
            res = plugin_module.handle("view.action",
                                       {"action": "configure-login-url",
                                        "payload": {"value": "https://login.lib.test"}})
            assert "登录页已更新" in res["message"]
            data = plugin_module._view_cfg()
            assert data["proxy_url"] == "http://proxy.lib.test:8080"
            assert data["login_url"] == "https://login.lib.test"
            # describe 回显输入值
            res = plugin_module.handle("view.describe", {})
            texts = {c["id"]: c for c in res["view"]["components"] if c["type"] == "text"}
            assert texts["proxy-input"]["value"] == "http://proxy.lib.test:8080"
            assert texts["login-url-input"]["value"] == "https://login.lib.test"
        finally:
            plugin_module._set_state_dir(Path("."))

    def test_panel_proxy_used_by_after_run_retry(self, tmp_path, monkeypatch):
        """GUI 用户在面板选好代理后，_after_run 的重试阶段自动使用该代理。"""
        plugin_module._set_state_dir(tmp_path)
        try:
            plugin_module._view_cfg_save({"proxy_url": "http://proxy.lib.test:8080", "message": ""})
            seen = []
            monkeypatch.setattr(plugin_module, "_rerun_failed",
                                lambda cfg, ws, results, failed, fp, runner, label:
                                seen.append(cfg) or ([], []))
            monkeypatch.setattr(plugin_module, "_generate_report", lambda *a, **k: None)
            plugin_module._after_run({"workspace": str(tmp_path), "config": {"retry_prompt_proxy": False},
                                      "results": [], "failed": [{"doi": "10.1/x", "error_class": "auth_required"}]})
            assert seen, "应触发重试"
            assert seen[0]["institution"]["proxy_url"] == "http://proxy.lib.test:8080"
        finally:
            plugin_module._set_state_dir(Path("."))


class TestViewRunSync:
    def test_run_config_syncs_login_url_and_proxy(self, tmp_path):
        plugin_module._set_state_dir(tmp_path)
        try:
            plugin_module._view_sync_from_run(
                {"institution": {"login_url": "https://login.lib.test",
                                 "proxy_url": "http://proxy.lib.test:8080"}},
                tmp_path)
            data = plugin_module._view_cfg()
            assert data["login_url"] == "https://login.lib.test"
            assert data["proxy_url"] == "http://proxy.lib.test:8080"
            assert data["workspace"] == str(tmp_path)
        finally:
            plugin_module._set_state_dir(Path("."))

    def test_open_login_success_flow(self, tmp_path, monkeypatch):
        """填写 login_url 后点按钮：后台线程执行登录并回写消息。"""
        plugin_module._set_state_dir(tmp_path)
        try:
            plugin_module._view_cfg_save({"login_url": "https://login.test", "message": ""})
            monkeypatch.setattr(plugin_module, "_login_and_capture_cookie",
                                lambda cfg: [{"name": "sid", "value": "v", "expires": -1}])
            res = plugin_module.handle("view.action", {"action": "open-login"})
            assert "登录窗口已打开" in res["message"]
            # 等待后台线程收尾（monkeypatch 版本应立即完成）
            import time
            for _ in range(50):
                if plugin_module._LOGIN_THREAD is None:
                    break
                time.sleep(0.05)
            data = plugin_module._view_cfg()
            assert "登录成功" in data["message"]
        finally:
            plugin_module._set_state_dir(Path("."))
