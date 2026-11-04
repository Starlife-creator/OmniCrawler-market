"""v0.9.0 view 面板契约测试。

v0.9.0 架构变更（宿主安全边界迁移）：
- 登录窗口 / 清除登录态按钮已移除（宿主 SDK 无交互浏览器/登录会话能力，
  且禁止插件把 Cookie 写入插件 state）——open-login 动作保留但必须返回
  明确的降级信息，不得再启动任何线程或浏览器。
- 机构代理字段保留为只读展示（宿主 network.fetch 不应用代理配置，
  下载一律经宿主 EgressBroker）。
本文件不得再断言登录窗口可用——那属于旧契约，断言即红。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module


class TestViewDescribe:
    def test_descriptor_shape(self):
        res = plugin_module.handle("view.describe", {})
        view = res["view"]
        assert view["view_id"] == "academic-paper-downloader.main"
        ids = [c["id"] for c in view["components"]]
        # v0.9.0：open-login / clear-login / login-url-input 已移除
        assert ids == ["status", "capability-note", "proxy-input",
                       "refresh", "message", "cancel-downloads"]
        texts = {c["id"]: c for c in view["components"] if c["type"] == "text"}
        assert texts["proxy-input"]["action"] == "configure-proxy"
        # 反向守卫：登录类组件不得出现
        assert "open-login" not in ids
        assert "clear-login" not in ids
        assert "login-url-input" not in ids

    def test_cookie_status_reflects_degradation(self, tmp_path):
        """v0.9.0 契约：登录态状态如实说明不支持，不得声称有/无登录态。"""
        plugin_module._set_state_dir(tmp_path)
        try:
            res = plugin_module.handle("view.describe", {})
            status = next(c for c in res["view"]["components"] if c["id"] == "status")
            assert "机构登录不支持" in status["text"]
        finally:
            plugin_module._set_state_dir(Path("."))


class TestViewActions:
    def test_open_login_is_explicitly_unsupported(self, tmp_path):
        """v0.9.0 契约：open-login 必须返回明确降级信息，不得弹窗/起线程。"""
        plugin_module._set_state_dir(tmp_path)
        try:
            res = plugin_module.handle("view.action", {"action": "open-login"})
            assert "机构登录不支持" in res["message"]
            # 不得残留任何登录线程引用
            assert not hasattr(plugin_module, "_LOGIN_THREAD")
        finally:
            plugin_module._set_state_dir(Path("."))

    def test_clear_login_reports_cleared_without_cookie_store(self, tmp_path):
        """v0.9.0 契约：clear-login 只清面板视图状态；Cookie 根本不存储。"""
        plugin_module._set_state_dir(tmp_path)
        try:
            config = {"institution": {"proxy_url": "http://proxy.lib.test:8080"}}
            res = plugin_module.handle("view.action", {"action": "clear-login"})
            assert "登录态已清除" in res["message"]
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
        """U4：面板 text 组件（configure-proxy）持久化输入值并回显。"""
        plugin_module._set_state_dir(tmp_path)
        try:
            res = plugin_module.handle("view.action",
                                       {"action": "configure-proxy",
                                        "payload": {"value": "http://proxy.lib.test:8080"}})
            assert "proxy.lib.test" in res["message"]
            data = plugin_module._view_cfg()
            assert data["proxy_url"] == "http://proxy.lib.test:8080"
            # describe 回显输入值
            res = plugin_module.handle("view.describe", {})
            texts = {c["id"]: c for c in res["view"]["components"] if c["type"] == "text"}
            assert texts["proxy-input"]["value"] == "http://proxy.lib.test:8080"
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
    def test_run_config_syncs_proxy(self, tmp_path):
        plugin_module._set_state_dir(tmp_path)
        try:
            plugin_module._view_sync_from_run(
                {"institution": {"proxy_url": "http://proxy.lib.test:8080"}},
                tmp_path)
            data = plugin_module._view_cfg()
            assert data["proxy_url"] == "http://proxy.lib.test:8080"
            assert data["workspace"] == str(tmp_path)
        finally:
            plugin_module._set_state_dir(Path("."))
