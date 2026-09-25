"""配置校验测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _validate_config


class TestConfigValidation:
    def test_valid_level_1(self):
        config = {"level": 1}
        errors = _validate_config(config)
        assert errors == []

    def test_valid_level_2(self):
        config = {"level": 2, "unpaywall_email": "test@example.com"}
        errors = _validate_config(config)
        assert errors == []

    def test_invalid_level(self):
        config = {"level": 4}
        errors = _validate_config(config)
        assert any("level 必须是 1/2/3" in e for e in errors)

    def test_level_3_missing_proxy(self):
        """v0.3.2：Level 3 不再要求 proxy_url/login_url 前置配置——
        直接用当前网络尝试，结果判定（校园网成功/普通网络失败记录原因）。"""
        config = {"level": 3, "institution": {"login_url": "https://login.example.com"}}
        errors = _validate_config(config)
        assert errors == []

    def test_level_3_missing_login_url(self):
        config = {"level": 3, "institution": {"proxy_url": "http://proxy.example.com"}}
        errors = _validate_config(config)
        assert errors == []

    def test_level_3_bare_config_accepted(self):
        """全自动模式：裸 Level 3（无 proxy/login/campus_ip）也合法。"""
        config = {"level": 3}
        errors = _validate_config(config)
        assert errors == []

    def test_level_3_valid(self):
        config = {"level": 3, "institution": {"proxy_url": "http://proxy.example.com", "login_url": "https://login.example.com"}}
        errors = _validate_config(config)
        assert errors == []

    def test_delay_min_too_small(self):
        config = {"delay_min": 0}
        errors = _validate_config(config)
        assert any("delay_min 建议 >= 1" in e for e in errors)

    def test_max_per_session_too_large(self):
        config = {"max_per_session": 500}
        errors = _validate_config(config)
        assert any("max_per_session 建议 <= 200" in e for e in errors)

    def test_level_3_campus_ip_relaxes_login_and_proxy(self):
        """校园直连模式：无需 proxy 与 login_url。"""
        config = {"level": 3, "campus_ip": True}
        errors = _validate_config(config)
        assert errors == []

    def test_level_3_institution_campus_ip_accepted(self):
        config = {"level": 3, "institution": {"campus_ip": True}}
        errors = _validate_config(config)
        assert errors == []
