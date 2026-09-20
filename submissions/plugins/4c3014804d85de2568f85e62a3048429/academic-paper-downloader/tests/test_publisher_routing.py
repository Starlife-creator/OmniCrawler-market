"""出版商路由配置测试。"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _PUBLISHERS, _RATE_LIMITER


class TestPublisherRouting:
    def test_all_publishers_have_prefix(self):
        for name, cfg in _PUBLISHERS.items():
            assert cfg.get("doi_prefix"), f"{name} missing doi_prefix"

    def test_all_publishers_have_home(self):
        for name, cfg in _PUBLISHERS.items():
            assert cfg.get("home"), f"{name} missing home"

    def test_all_publishers_have_rate_limit(self):
        for name, cfg in _PUBLISHERS.items():
            assert cfg.get("rate_limit", 0) > 0, f"{name} missing rate_limit"

    def test_all_publishers_have_auth_method(self):
        valid_methods = {"none", "proxy", "cookie", "saml", "shibboleth"}
        for name, cfg in _PUBLISHERS.items():
            method = cfg.get("auth_method")
            assert method in valid_methods, f"{name} has invalid auth_method: {method}"

    def test_config_file_exists(self):
        config_path = Path(__file__).resolve().parents[1] / "config" / "publishers.yaml"
        assert config_path.exists()

    def test_config_file_valid_yaml(self):
        config_path = Path(__file__).resolve().parents[1] / "config" / "publishers.yaml"
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "publishers" in data


class TestRateLimiter:
    def test_wait_no_block(self):
        # 不应阻塞
        _RATE_LIMITER.wait("mdpi")  # rate_limit=1.0
        _RATE_LIMITER.wait("mdpi")

    def test_unknown_publisher(self):
        _RATE_LIMITER.wait("unknown")  # 不应抛出异常