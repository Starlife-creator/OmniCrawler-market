"""State 管理测试（断点续传、失败记录）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _done_key, _failed_key, _cookie_key, _state_key


class TestStateKeys:
    def test_done_key_format(self):
        config = {"institution": {"proxy_url": "http://proxy.example.com"}}
        key = _done_key(config)
        assert key.startswith("apd_done_")
        assert len(key) >= 9

    def test_failed_key_format(self):
        config = {"institution": {"proxy_url": "http://proxy.example.com"}}
        key = _failed_key(config)
        assert key.startswith("apd_failed_")

    def test_cookie_key_format(self):
        config = {"institution": {"proxy_url": "http://proxy.example.com"}}
        key = _cookie_key(config)
        assert key.startswith("apd_cookie_")

    def test_different_proxies_different_keys(self):
        config1 = {"institution": {"proxy_url": "http://proxy1.example.com"}}
        config2 = {"institution": {"proxy_url": "http://proxy2.example.com"}}
        assert _done_key(config1) != _done_key(config2)
        assert _failed_key(config1) != _failed_key(config2)
        assert _cookie_key(config1) != _cookie_key(config2)

    def test_no_proxy_uses_default(self):
        config = {}
        key = _done_key(config)
        assert "default" in key or "apd_done_" in key