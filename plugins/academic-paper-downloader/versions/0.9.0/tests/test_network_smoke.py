"""真实网络冒烟：真实 OA PDF 下载 + 校验 + 交付（离线自动 skip）。

生产实测发现：MDPI / RSC 对脚本化请求返回 403 bot 拦截（content-type=text/html）。
本测试改用不拦截脚本的 arXiv 真实 OA PDF 验证完整下载交付链路。

v0.9.0：网络路径全部经宿主 EgressBroker（_host_fetch → network.fetch），
PDF 经宿主 artifact.stream 交付（_host_save_pdf），本地 workspace 不再留 PDF。
独立运行（无宿主 SDK）时 skip——因为本测试验证的是"真实网络 + 宿主交付"，
缺失任一环节都不构成有效证据。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module

REAL_ARXIV_URL = "https://arxiv.org/pdf/2101.00001"


def _has_host_sdk() -> bool:
    """v0.9.0：真实网络冒烟需要宿主 SDK（否则直连被拒，链路不成立）。"""
    try:
        import importlib.util
        return importlib.util.find_spec("omnicrawler_sdk") is not None
    except Exception:
        return False


def _online() -> bool:
    try:
        import httpx
        with httpx.stream("GET", REAL_ARXIV_URL, follow_redirects=True,
                          timeout=10) as r:
            return r.status_code == 200 and "pdf" in (r.headers.get("content-type") or "")
    except Exception:
        return False


requires_network = pytest.mark.skipif(
    not (_online() and _has_host_sdk()),
    reason="no reachable network / arXiv blocked / no host SDK (v0.9.0 requires host EgressBroker+artifact)")


class TestNetworkSmoke:
    @requires_network
    def test_real_arxiv_download_stream(self):
        """真实网络：经宿主 EgressBroker 抓取返回真实 PDF 字节。"""
        headers = plugin_module._build_headers("arxiv")
        content, status = plugin_module._fetch_pdf(REAL_ARXIV_URL, headers, timeout=30)
        assert status == 200
        assert content and content.startswith(b"%PDF")

    @requires_network
    def test_retry_pipeline_real_download(self):
        """真实网络：_download_with_retry 全链路（重试/分类逻辑真实执行）。"""
        paper = {"doi": "10.48550/arXiv.2101.00001", "publisher": "arxiv"}
        content, error = plugin_module._download_with_retry(
            REAL_ARXIV_URL, paper, {"retry_count": 1}, {})
        assert error == "ok"
        assert content and content.startswith(b"%PDF")

    @requires_network
    def test_process_download_real_save(self, tmp_path, monkeypatch):
        """真实网络 + 真实交付：monkeypatch 仅注入 OA URL 与轻量 PDF 校验。"""
        monkeypatch.setattr(plugin_module, "_try_oa_direct",
                            lambda doi, pub, is_oa: REAL_ARXIV_URL)
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_validate_pdf",
                            lambda p: p.read_bytes()[:4] == b"%PDF")
        monkeypatch.setattr(plugin_module, "_mark_done", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)

        paper = {"doi": "10.48550/arXiv.2101.00001", "title": "High-Entropy Alloys",
                 "first_author": "Yeh", "year": "2004", "publisher": "arxiv", "is_oa": True}
        res = plugin_module._process_download(paper, {"level": 1, "retry_count": 1},
                                              Path(tmp_path), {"done": 0, "total": 1})
        assert res["records"] and res["records"][0]["doi"] == "10.48550/arXiv.2101.00001"
        assert res["records"][0]["download_source"] == "oa_direct"
        # v0.9.0：交付宿主 artifact（不得再断言 workspace 本地 PDF 文件）
        assert res["records"][0]["artifact_id"], "必须交付宿主 artifact"
        assert res["records"][0]["local_path"] == "", "v0.9.0 本地 workspace 不留 PDF"
