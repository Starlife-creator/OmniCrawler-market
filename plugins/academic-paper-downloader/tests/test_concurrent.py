"""并发控制与批量报告测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _ConcurrencyController, _generate_report, _RateLimiter


class TestConcurrencyController:
    def test_active_count(self):
        ctrl = _ConcurrencyController(2)
        assert ctrl.active == 0

    def test_acquire_release(self):
        ctrl = _ConcurrencyController(2)
        ctrl.acquire()
        assert ctrl.active == 1
        ctrl.release()
        assert ctrl.active == 0

    def test_acquire_blocks_above_max(self):
        """超过上限时 acquire 应阻塞直到释放。"""
        import threading
        ctrl = _ConcurrencyController(1)
        ctrl.acquire()
        got = []
        def worker():
            ctrl.acquire()
            got.append(True)
            ctrl.release()
        t = threading.Thread(target=worker)
        t.start()
        import time
        time.sleep(0.2)
        assert got == []  # 仍在阻塞
        ctrl.release()
        t.join(timeout=2)
        assert got == [True]

    def test_context_manager(self):
        ctrl = _ConcurrencyController(2)
        with ctrl:
            assert ctrl.active == 1
        assert ctrl.active == 0

    def test_default_max(self):
        ctrl = _ConcurrencyController()
        assert ctrl._max == 3


class TestRateLimiter:
    def test_no_block_fast(self):
        """限流器不应阻塞过快请求。"""
        rl = _RateLimiter()
        rl.wait("mdpi")  # rate_limit=1.0
        rl.wait("mdpi")
        # 不应抛出异常

    def test_unknown_publisher(self):
        rl = _RateLimiter()
        rl.wait("unknown")  # 不应抛出异常


class TestBatchReport:
    def test_generate_report(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            results = [{"doi": "10.1039/test", "title": "Test", "local_path": "papers/test.pdf"}]
            failed = [{"doi": "10.9999/fail", "reason": "timeout"}]
            _generate_report(workspace, results, failed)
            # 检查报告文件存在
            report_dir = workspace / "reports"
            assert report_dir.exists()
            csv_files = list(report_dir.glob("*.csv"))
            assert len(csv_files) >= 1
            html_files = list(report_dir.glob("*.html"))
            assert len(html_files) >= 1