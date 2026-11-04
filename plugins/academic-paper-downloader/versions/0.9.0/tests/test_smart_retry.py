"""智能重试分类测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _classify_error, _retry_strategy


class TestErrorClassification:
    def test_429_is_rate_limit(self):
        assert _classify_error(429, None) == "rate_limit"

    def test_500_is_server_error(self):
        assert _classify_error(500, None) == "server_error"

    def test_503_is_server_error(self):
        assert _classify_error(503, None) == "server_error"

    def test_403_is_auth_required(self):
        assert _classify_error(403, None) == "auth_required"

    def test_403_subscription_publisher_is_auth_required(self):
        assert _classify_error(403, None, "elsevier") == "auth_required"

    def test_403_free_oa_publisher_is_bot_blocked(self):
        """OA 源（auth_method=none）的 403 是反爬，不是授权失败。"""
        assert _classify_error(403, None, "mdpi") == "bot_blocked"
        assert _classify_error(401, None, "arxiv") == "bot_blocked"

    def test_200_landing_subscription_is_auth_required(self):
        """订阅源 200-非PDF（登录墙/落地页）→ 认证失效，触发重登。"""
        assert _classify_error(200, None, "elsevier") == "auth_required"

    def test_200_landing_free_oa_is_bot_blocked(self):
        """OA 源 200-非PDF（反爬落地页）→ bot_blocked，不触发重登。"""
        assert _classify_error(200, None, "mdpi") == "bot_blocked"

    def test_timeout_is_network(self):
        assert _classify_error(None, "timeout") == "network"

    def test_connection_is_network(self):
        assert _classify_error(None, "connection") == "network"

    def test_captcha_is_captcha(self):
        assert _classify_error(None, "captcha") == "captcha"

    def test_unknown_fallback(self):
        assert _classify_error(None, "unknown") == "unknown"


class TestRetryStrategy:
    def test_rate_limit_exponential(self):
        """429 退避乘以 3。"""
        delay = _retry_strategy("rate_limit", 1, {"retry_base_delay": 2.0, "retry_max_delay": 60.0})
        assert delay is not None
        assert delay > 4.0  # 2 * 2 * 3 = 12, but capped differently

    def test_server_error_basic(self):
        delay = _retry_strategy("server_error", 0, {"retry_base_delay": 2.0})
        assert delay is not None and delay <= 2.0

    def test_auth_required_no_retry(self):
        """403 不重试。"""
        delay = _retry_strategy("auth_required", 0, {"retry_base_delay": 2.0})
        assert delay is None

    def test_bot_blocked_no_retry_channel_upgrade_instead(self):
        """v0.4.0 起 bot_blocked 是通道不匹配信号：同通道重试无意义，交给通道升级。"""
        assert _retry_strategy("bot_blocked", 0, {"retry_base_delay": 2.0}) is None
        assert _retry_strategy("bot_blocked", 1, {"retry_base_delay": 2.0}) is None

    def test_max_retries_exceeded(self):
        """超过最大重试次数不重试。"""
        delay = _retry_strategy("network", 5, {"retry_base_delay": 2.0, "retry_count": 3})
        assert delay is None

    def test_network_exponential(self):
        delay = _retry_strategy("network", 0, {"retry_base_delay": 2.0})
        assert delay is not None and delay <= 2.0

    def test_captcha_no_retry_channel_upgrade_instead(self):
        """v0.4.0 起 captcha 同样交给通道升级（可见浏览器内人工通过），不再空转退避。"""
        assert _retry_strategy("captcha", 0, {"retry_base_delay": 2.0}) is None
