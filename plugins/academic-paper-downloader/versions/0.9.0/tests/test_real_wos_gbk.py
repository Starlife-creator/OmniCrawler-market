"""真实 WoS 导出端到端：官方两字母字段码头 + GBK 编码（中文系统）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin as plugin_module


# WoS 官方 TSV 导出头（两字母字段码）
WOS_HEADER = ["PT", "AU", "AF", "TI", "SO", "LA", "DT", "DE", "AB",
              "C1", "PU", "SN", "DI", "PY"]

ROWS = [
    ["J", "Zhang, San", "Zhang, San; Li, Si", "玻璃材料结构分析",
     "Materials", "English", "Article", "structure; glass",
     "An abstract about glass materials.", "[Zhang, San] Univ X",
     "MDPI", "1996-1944", "10.3390/ma16010001", "2023"],
    ["J", "Wang, Wu", "Wang, Wu", "IEEE circuits in power systems",
     "IEEE Transactions", "English", "Article", "circuit",
     "An abstract.", "[Wang, Wu] Univ Y",
     "IEEE", "0018-9219", "10.1109/jproc.2022.1", "2022"],
]


def _make_wos_tsv(path: Path, encoding: str = "gb18030") -> Path:
    text = "\t".join(WOS_HEADER) + "\n" + "".join("\t".join(r) + "\n" for r in ROWS)
    path.write_bytes(text.encode(encoding))
    return path


class TestRealWosGbk:
    def test_gb18030_bytes_decoded_correctly(self, tmp_path):
        """中文系统导出的 GBK TSV 应正确解码为 Unicode。"""
        path = _make_wos_tsv(tmp_path / "savedrecs.tsv")
        text = plugin_module._decode_bytes(path.read_bytes())
        assert text is not None
        assert "玻璃材料结构分析" in text

    def test_utf8_without_bom_decoded(self, tmp_path):
        path = _make_wos_tsv(tmp_path / "u8.tsv", encoding="utf-8")
        assert "玻璃材料结构分析" in plugin_module._decode_bytes(path.read_bytes())

    def test_wos_field_codes_normalized(self, tmp_path):
        path = _make_wos_tsv(tmp_path / "savedrecs.tsv")
        chunks = plugin_module._parse_input_file_chunked(str(path))
        rows = [r for chunk in chunks for r in chunk]
        assert len(rows) == 2
        row0 = rows[0]
        # 字段码头 → 规范列名（TI→Article Title, DI→DOI, AU→Authors, AF→Author Full Names, SN→ISSN）
        assert row0["Article Title"] == "玻璃材料结构分析"
        assert row0["DOI"] == "10.3390/ma16010001"
        assert row0["Authors"] == "Zhang, San"             # AU
        assert row0["Author Full Names"] == "Zhang, San; Li, Si"  # AF
        assert row0["ISSN"] == "1996-1944"
        assert row0["Publication Year"] == "2023"

    def test_extract_doi_via_value_scan(self, tmp_path):
        """即使无字段码头映射，DOI 值扫描兜底也能命中。"""
        path = tmp_path / "plain.tsv"
        path.write_bytes("DOI\n10.1007/978-3-030-00000-0\n".encode("utf-8"))
        rows = plugin_module._parse_input_file(str(path))
        assert plugin_module._extract_doi(rows[0]) == "10.1007/978-3-030-00000-0"

    def test_seed_full_e2e_gbk(self, tmp_path):
        """GBK 真实 WoS 文件 → seed 全链路（解析 + 路由 + OA ISSN 白名单）。"""
        path = _make_wos_tsv(tmp_path / "savedrecs.tsv")
        res = plugin_module._seed({"file_path": str(path), "workspace": str(tmp_path),
                                   "config": {"level": 1, "incremental": False}})
        assert res["errors"] == []
        assert res["meta"]["total_papers"] == 2
        by_doi = {r["meta"]["paper"]["doi"]: r["meta"]["paper"] for r in res["requests"]}
        mdpi = by_doi["10.3390/ma16010001"]
        assert mdpi["publisher"] == "mdpi"
        assert mdpi["is_oa"] is True              # ISSN 1996-1944 白名单
        assert mdpi["first_author"] == "Zhang"
        assert "玻璃材料结构分析" in mdpi["title"]  # GBK 中文标题保留
        ieee = by_doi["10.1109/jproc.2022.1"]
        assert ieee["publisher"] == "ieee"
        assert ieee["is_oa"] is False

    def test_seed_incremental_skips_done(self, tmp_path, monkeypatch):
        """增量模式：已下载 DOI 不重复入队。"""
        path = _make_wos_tsv(tmp_path / "savedrecs.tsv")
        done_value = '[{"doi": "10.3390/ma16010001", "title": "x"}]'

        class FakeSDK:
            @staticmethod
            def call(op, payload=None):
                if op == "state.get":
                    return {"value": done_value}
                return None

        monkeypatch.setitem(sys.modules, "omnicrawler_sdk", FakeSDK)
        res = plugin_module._seed({"file_path": str(path), "workspace": str(tmp_path),
                                   "config": {"level": 1, "incremental": True}})
        dois = {r["meta"]["paper"]["doi"] for r in res["requests"]}
        assert dois == {"10.1109/jproc.2022.1"}
