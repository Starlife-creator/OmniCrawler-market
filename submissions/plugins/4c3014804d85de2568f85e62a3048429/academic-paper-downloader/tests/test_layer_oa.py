"""Layer 1: OA 直连测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _try_oa_direct


class TestLayerOa:
    def test_unknown_publisher(self):
        assert _try_oa_direct("99.9999/test", "unknown") is None

    def test_no_oa_pattern(self):
        assert _try_oa_direct("10.1109/TWC.2023.3250267", "ieee") is None

    def test_returns_url_without_network(self, monkeypatch):
        """OA 层只构造 URL，不联网探测（避免 PDF 双下载）。"""
        called = {"get": False}

        def fake_get(*a, **k):
            called["get"] = True
            return None

        monkeypatch.setattr("httpx.get", fake_get)
        url = _try_oa_direct("10.3390/ma16010001", "mdpi", is_oa=True)
        assert url == "https://www.mdpi.com/10.3390/ma16010001/pdf"
        assert called["get"] is False

    def test_returns_none_when_not_oa(self):
        assert _try_oa_direct("10.3390/ma16010001", "mdpi", is_oa=False) is None