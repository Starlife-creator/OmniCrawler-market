"""登录态监控与分布式锁测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _CookieMonitor, _DistributedLock


class TestCookieMonitor:
    def test_invalid_when_no_cookies(self):
        monitor = _CookieMonitor({"institution": {}})
        assert monitor.is_valid() is False

    def test_monitor_cycling(self):
        """多次调用不应抛出异常。"""
        monitor = _CookieMonitor({"institution": {}})
        monitor.is_valid()
        monitor.is_valid()
        # 正常执行即可

    def test_refresh_returns_none_when_no_cookies(self):
        monitor = _CookieMonitor({"institution": {}})
        result = monitor.refresh_if_needed()
        assert result is None


class TestDistributedLock:
    def test_lock_key_format(self):
        lock = _DistributedLock({"institution": {"proxy_url": "http://test"}})
        key = lock._key
        assert "apd_lock_" in key

    def test_acquire_degrade_on_sdk_error(self):
        """SDK 不可用时降级为允许下载。"""
        lock = _DistributedLock({})
        result = lock.acquire("99.9999/test")
        assert result is True  # 降级