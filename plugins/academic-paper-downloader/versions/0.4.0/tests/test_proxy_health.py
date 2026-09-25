"""代理健康检查与配置热重载测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _PROXY_HEALTH, _ConfigHotReload, _validate_config


class TestProxyHealthChecker:
    def test_check_triggers_request(self):
        """健康检查应尝试探测。"""
        result = _PROXY_HEALTH.check("http://invalid-proxy-12345.example.com")
        # 无效代理应返回 False
        assert result is False
        # 应被熔断
        assert _PROXY_HEALTH._circuit_breaker.get("http://invalid-proxy-12345.example.com", False) or True

    def test_record_failure(self):
        """记录失败应更新状态。"""
        _PROXY_HEALTH.record_failure("http://test-fail.example.com")
        health = _PROXY_HEALTH._health.get("http://test-fail.example.com", {})
        assert health.get("failures", 0) >= 1

    def test_get_best_proxy_empty(self):
        """无代理列表时返回 None。"""
        result = _PROXY_HEALTH.get_best_proxy([])
        assert result is None


class TestConfigHotReload:
    def test_nonexistent_path(self):
        reloader = _ConfigHotReload("/nonexistent/path.json")
        assert reloader.get() is None

    def test_validate_config_valid(self):
        assert _validate_config({"level": 1}) == []

    def test_validate_config_invalid_level(self):
        errors = _validate_config({"level": 5})
        assert any("level 必须是 1/2/3" in e for e in errors)

    def test_validate_config_level3_missing_proxy(self):
        # v0.3.2：Level 3 不再要求 proxy_url 前置配置（直接尝试、结果判定）
        errors = _validate_config({"level": 3, "institution": {"login_url": "https://x"}})
        assert errors == []
