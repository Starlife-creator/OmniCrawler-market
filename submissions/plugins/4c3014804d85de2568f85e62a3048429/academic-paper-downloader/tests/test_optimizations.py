"""回归测试：OpenAlex 预检修复 / 配置热重载 / .xls 兜底 / 流式落盘 / 大小上限 / 注入转义 / state 分键。

对应 v0.3.0 优化项，全部离线（mock 网络与 SDK）。
"""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module


class _FakeSDK:
    """内存版 omnicrawler_sdk：state.get/set/delete + 幂等读改写。"""

    def __init__(self):
        self.store = {}

    def call(self, op, payload=None):
        payload = payload or {}
        if op == "state.get":
            return {"value": self.store.get(payload.get("key"))}
        if op == "state.set":
            self.store[payload.get("key")] = payload.get("value")
            return {}
        if op == "state.delete":
            self.store.pop(payload.get("key"), None)
            return {}
        return None


def _install_sdk(monkeypatch, sdk=None):
    sdk = sdk or _FakeSDK()
    monkeypatch.setitem(sys.modules, "omnicrawler_sdk", sdk)
    return sdk


class TestOpenAlexPrecheck:
    def test_batch_check_uses_doi_keys(self, monkeypatch):
        """预检结果按 DOI 键回填（修复 id 字段是 OpenAlex Work ID 而非 DOI 的问题）。"""
        by_doi = {
            "10.3390/ma16010001": True,
            "10.1039/d4ta07735a": False,
            "10.1007/test.1": False,
        }
        monkeypatch.setattr(plugin_module, "_fetch_oa_status", lambda d: (d, by_doi.get(d, False)))
        res = plugin_module._batch_check_oa(list(by_doi))
        assert res["10.3390/ma16010001"] is True
        assert res["10.1039/d4ta07735a"] is False
        assert res["10.1007/test.1"] is False

    def test_fetch_oa_status_parses_real_style_response(self, monkeypatch):
        """真实响应形态：results[].doi 是 https://doi.org/... 前缀，需剥去再做键。"""
        def fake_get(url, **kw):
            return _FakeResp200({"results": [
                {"id": "https://openalex.org/W4312078660",
                 "doi": "https://doi.org/10.3390/ma16010001",
                 "open_access": {"oa_status": "gold"}},
            ]})
        monkeypatch.setattr(httpx, "get", fake_get)
        assert plugin_module._fetch_oa_status("10.3390/ma16010001") == ("10.3390/ma16010001", True)

    def test_seed_precheck_skips_free_oa(self, tmp_path, monkeypatch):
        """seed 只对真正不确定的 DOI 做预检；免费 OA 信号直接命中不回发请求。"""
        _install_sdk(monkeypatch)
        tsv = tmp_path / "in.tsv"
        tsv.write_text(
            "DOI\tISSN\n"
            "10.3390/free.1\t1996-1944\n"             # ISSN 白名单 → 不需预检
            "10.48550/arXiv.2211.00001\t\n"           # arxiv 全 OA → 不需预检
            "10.1007/s00894-025-06304-z\t0000-0000\n",  # 未知 → 需要预检
            encoding="utf-8")
        seen = []
        monkeypatch.setattr(plugin_module, "_batch_check_oa_sync",
                            lambda dois: seen.extend(dois) or {"10.1007/s00894-025-06304-z": True})
        res = plugin_module._seed({"file_path": str(tsv), "workspace": str(tmp_path),
                                   "config": {"level": 2, "incremental": False}})
        assert seen == ["10.1007/s00894-025-06304-z"]
        by_doi = {r["meta"]["paper"]["doi"]: r["meta"]["paper"] for r in res["requests"]}
        assert by_doi["10.3390/free.1"]["is_oa"] is True
        assert by_doi["10.48550/arxiv.2211.00001"]["is_oa"] is True  # DOI 统一小写
        assert by_doi["10.1007/s00894-025-06304-z"]["is_oa"] is True

    def test_precheck_capped(self, monkeypatch, tmp_path):
        _install_sdk(monkeypatch)
        monkeypatch.setattr(plugin_module, "_OA_PRECHECK_LIMIT", 2)
        rows = "\n".join(f"10.1007/x.{i}\t0000-0000" for i in range(10))
        tsv = tmp_path / "big.tsv"
        tsv.write_text("DOI\tISSN\n" + rows + "\n", encoding="utf-8")
        called = []
        monkeypatch.setattr(plugin_module, "_batch_check_oa_sync",
                            lambda dois: called.extend(dois) or {})
        res = plugin_module._seed({"file_path": str(tsv), "workspace": str(tmp_path),
                                   "config": {"level": 2, "incremental": False}})
        assert len(called) == 2


class TestConfigHotReload:
    def test_commented_yaml_now_loads(self, tmp_path, monkeypatch):
        """带 # 注释头的 publishers.yaml 之前无法重载，现在应正常装载。"""
        cfg = tmp_path / "publishers.yaml"
        cfg.write_text("# 注释行\npublishers:\n  mdpi:\n    rate_limit: 9.0\n", encoding="utf-8")
        monkeypatch.setattr(plugin_module, "_PUBLISHERS_CONFIG", cfg)
        monkeypatch.setattr(plugin_module, "_PUBLISHERS_RELOADER",
                            plugin_module._ConfigHotReload(str(cfg)))
        assert plugin_module._reload_publishers_config() is True
        assert plugin_module._PUBLISHERS["mdpi"]["rate_limit"] == 9.0

    def test_commented_yaml_keeps_defaults_for_undeclared(self, tmp_path, monkeypatch):
        cfg = tmp_path / "publishers.yaml"
        cfg.write_text("# c\npublishers:\n  mdpi:\n    rate_limit: 9.0\n", encoding="utf-8")
        monkeypatch.setattr(plugin_module, "_PUBLISHERS_CONFIG", cfg)
        monkeypatch.setattr(plugin_module, "_PUBLISHERS_RELOADER",
                            plugin_module._ConfigHotReload(str(cfg)))
        plugin_module._reload_publishers_config()
        assert plugin_module._PUBLISHERS["mdpi"]["home"] == "https://www.mdpi.com"


class TestXlsGraceful:
    def test_legacy_xls_does_not_crash(self, tmp_path):
        """旧版 BIFF .xls（无 xlrd）应静默返回 []，而不是抛异常打崩 seed。"""
        p = tmp_path / "legacy.xls"
        p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 128)
        assert plugin_module._parse_input_file(str(p)) == []
        assert list(plugin_module._parse_input_file_chunked(str(p))) == []

    def test_xls_extensions_accepted_by_seed(self, tmp_path, monkeypatch):
        _install_sdk(monkeypatch)
        os_name = tmp_path / "x.xls"
        os_name.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 128)
        res = plugin_module._seed({"file_path": str(os_name), "workspace": str(tmp_path),
                                   "config": {"level": 1}})
        assert res["errors"][0]["reason"] == "empty_or_unreadable"


class _FakeResp200:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data


class _FakeStreamResp:
    def __init__(self, chunks, status=200, content_type="application/pdf"):
        self._chunks = chunks
        self.status_code = status
        self.headers = {"content-type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self, chunk_size=8192):
        for c in self._chunks:
            yield c


def _mock_http_client(monkeypatch, response):
    """把共享 HTTP 客户端替换为返回指定响应的 mock。"""
    mock_client = type("MockClient", (), {
        "stream": lambda *a, **k: response,
        "is_closed": False,
    })()
    monkeypatch.setattr(plugin_module, "_HTTP_CLIENT", mock_client)


class TestStreamDownloadAndCaps:
    def test_fetch_pdf_raises_on_size_limit(self, monkeypatch):
        monkeypatch.setattr(plugin_module, "_MAX_PDF_BYTES", 1024)
        _mock_http_client(monkeypatch, _FakeStreamResp([b"x" * 600, b"y" * 600]))
        with pytest.raises(plugin_module._PdfTooLarge):
            plugin_module._fetch_pdf("https://x.test/a.pdf", {}, {}, timeout=10)

    def test_stream_pdf_cleans_partial_on_limit(self, monkeypatch, tmp_path):
        monkeypatch.setattr(plugin_module, "_MAX_PDF_BYTES", 1024)
        _mock_http_client(monkeypatch, _FakeStreamResp([b"x" * 600, b"y" * 600]))
        dest = tmp_path / "a.part"
        out, status = plugin_module._stream_pdf("https://x.test/a.pdf", {}, {}, 10, dest)
        assert out is None
        assert not dest.exists()  # 超限部分文件已清理

    def test_stream_pdf_returns_dest_on_success(self, monkeypatch, tmp_path):
        _mock_http_client(monkeypatch, _FakeStreamResp([b"%PDF-1.4\n"]))
        dest = tmp_path / "a.part"
        out, status = plugin_module._stream_pdf("https://x.test/a.pdf", {}, {}, 10, dest)
        assert out is not None and out.exists()
        assert dest.read_bytes() == b"%PDF-1.4\n"

    def test_process_download_streams_to_tmp_then_moves(self, tmp_path, monkeypatch):
        """HTTP 下载走临时文件路径，成功后由 _save_pdf 移入 papers/。"""
        seen_dest = []

        def fake_stream(pdf_url, headers, cookies, timeout, dest):
            seen_dest.append(dest)
            Path(dest).write_bytes(b"%PDF-1.4\n%%EOF\nx")
            return Path(dest), 200

        monkeypatch.setattr(plugin_module, "_try_oa_direct",
                            lambda doi, pub, is_oa: "https://x.test/paper.pdf")
        monkeypatch.setattr(plugin_module, "_try_api_probe", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_stream_pdf", fake_stream)
        monkeypatch.setattr(plugin_module, "_validate_pdf", lambda p: True)
        monkeypatch.setattr(plugin_module, "_rename_with_metadata", lambda paper, p: p)
        monkeypatch.setattr(plugin_module, "_extract_pdf_meta", lambda p: {})
        monkeypatch.setattr(plugin_module, "_mark_done", lambda *a, **k: None)
        monkeypatch.setattr(plugin_module, "_mark_failed", lambda *a, **k: None)

        paper = {"doi": "10.3390/x", "title": "T", "first_author": "A",
                 "year": "2025", "publisher": "mdpi", "is_oa": True}
        res = plugin_module._process_download(paper, {"level": 1}, Path(tmp_path), {"done": 0, "total": 1})
        assert res["records"] and res["records"][0]["download_source"] == "oa_direct"
        assert len(seen_dest) == 1
        saved = Path(tmp_path) / res["records"][0]["local_path"]
        assert saved.is_file()
        assert not Path(seen_dest[0]).exists()  # 临时文件已移走


class TestEscaping:
    def test_csv_formula_injection_neutralized(self):
        assert plugin_module._csv_safe("=SUM(A1:A9)") == "'=SUM(A1:A9)"
        assert plugin_module._csv_safe("+22") == "'+22"
        assert plugin_module._csv_safe("normal") == "normal"

    def test_html_escaped(self):
        assert plugin_module._esc("a & b") == "a &amp; b"
        assert "<script>" not in plugin_module._esc("<script>alert(1)</script>")

    def test_report_output_is_injection_safe(self, tmp_path):
        plugin_module._generate_report(
            Path(tmp_path),
            [{"doi": "10.1007/x", "title": "<img onerror=x>", "local_path": "papers/a.pdf"}],
            [{"doi": "10.9999/f", "reason": "=cmd|' /C calc'!A0"}])
        html = (next((Path(tmp_path) / "reports").glob("dashboard_*.html"))).read_text(encoding="utf-8")
        csv = (next((Path(tmp_path) / "reports").glob("download_report_*.csv"))).read_text(encoding="utf-8-sig")
        assert "<img onerror=x>" not in html
        assert "&lt;img" in html
        assert "'=cmd|" in csv.splitlines()[2]  # 已加单引号前缀，防公式求值


class TestStatePerDoi:
    def test_mark_done_writes_record_key_and_doi_list(self, monkeypatch):
        sdk = _install_sdk(monkeypatch)
        config = {"institution": {"proxy_url": "http://proxy.example.com"}, "level": 1}
        rec = {"doi": "10.3390/x", "title": "T"}
        plugin_module._mark_done(config, "10.3390/x", rec)
        plugin_module._mark_done(config, "10.1007/y", {"doi": "10.1007/y"})
        done = json.loads(sdk.store[plugin_module._done_key(config)])
        assert done == ["10.3390/x", "10.1007/y"]  # 列表只存 DOI（字符串）
        assert len(done) == 2
        # per-DOI 完整记录可独立读取
        rec_key = plugin_module._record_key(config, "10.3390/x")
        assert json.loads(sdk.store[rec_key])["title"] == "T"

    def test_load_done_records_reconstructs(self, monkeypatch):
        sdk = _install_sdk(monkeypatch)
        config = {}
        plugin_module._mark_done(config, "10.3390/x", {"doi": "10.3390/x", "title": "X"})
        records, done_list = plugin_module._load_done_records(config)
        assert done_list == ["10.3390/x"]
        assert any(r.get("title") == "X" for r in records)

    def test_load_done_records_backward_compat_dict_list(self, monkeypatch):
        sdk = _install_sdk(monkeypatch)
        config = {}
        sdk.store[plugin_module._done_key(config)] = json.dumps([{"doi": "10.1007/old", "title": "Old"}])
        records, done_list = plugin_module._load_done_records(config)
        assert done_list == [{"doi": "10.1007/old", "title": "Old"}]
        assert records[0]["title"] == "Old"  # 旧格式 dict 列表仍可直接用