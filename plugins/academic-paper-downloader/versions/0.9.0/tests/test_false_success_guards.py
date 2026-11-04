"""「假成功」防护测试（issue #22 §1）——v0.9.0 适配宿主能力后仍锁定的性质：

- 反爬挑战页/登录页不会再被误判为成功（下载只经宿主 network.fetch + 严格 PDF 校验）；
- PDF 内提不出 DOI ⇒ 记录**保留**但标记 `verified=False`，**不计入成功**；
- DOI 不匹配 ⇒ 保留但 `verified=False`；
- 报告与 hook 返回值按同一口径计数（Success 不含未核验）；
- v0.9.0：PDF 交付宿主 artifact（`artifact_id`），本地 workspace 不留 PDF 副本；
  宿主 artifact 能力不可用时 `_save_pdf` 返回 None（明确降级，不静默落本地文件）。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin  # noqa: E402
from plugin import _generate_report, _save_pdf  # noqa: E402


def _stub_host_artifact(monkeypatch):
    """模拟宿主 artifact.stream：返回受控 artifact 引用。"""
    saved = {}

    def fake_host_save(filename, data, maximum_bytes=None):
        saved["filename"] = filename
        saved["size"] = len(data)
        return {
            "artifact_id": "sha256:" + ("0" * 64),
            "name": filename,
            "media_type": "application/pdf",
            "size": len(data),
            "sha256": "0" * 64,
        }

    monkeypatch.setattr(plugin, "_host_save_pdf", fake_host_save)
    return saved


def _save(tmp_path, monkeypatch, *, extracted_meta):
    monkeypatch.setattr("plugin._validate_pdf", lambda p: True)
    monkeypatch.setattr("plugin._rename_with_metadata", lambda paper, p: p)
    monkeypatch.setattr("plugin._extract_pdf_meta", lambda p: extracted_meta)
    _stub_host_artifact(monkeypatch)
    paper = {"doi": "10.1038/s41586-021-00001-2", "title": "T", "first_author": "A", "year": "2021"}
    return _save_pdf(paper, b"%PDF-1.4\n%%EOF\nx", Path(tmp_path), "oa_direct")


# --- DOI 核验：未核验保留但不计入成功 ----------------------------------------


def test_unverifiable_pdf_is_kept_but_marked_unverified(tmp_path, monkeypatch):
    record = _save(tmp_path, monkeypatch, extracted_meta={})

    assert record is not None, "arXiv/扫描版 PDF 本就提不出 DOI，不能误拒"
    assert record["verified"] is False
    assert record["verification"] == "doi_not_found_in_pdf"


def test_matched_doi_is_marked_verified(tmp_path, monkeypatch):
    record = _save(tmp_path, monkeypatch, extracted_meta={"extracted_doi": "10.1038/S41586-021-00001-2."})

    assert record is not None
    assert record["verified"] is True
    assert record["verification"] == "doi_matched"


def test_mismatched_doi_kept_as_unverified(tmp_path, monkeypatch):
    record = _save(tmp_path, monkeypatch, extracted_meta={"extracted_doi": "10.9999/other"})

    assert record is not None
    assert record["verified"] is False


def test_save_pdf_delivers_host_artifact_not_local_copy(tmp_path, monkeypatch):
    """v0.9.0 契约：PDF 交付宿主 artifact，record 带 artifact_id，本地临时文件已清理。"""
    monkeypatch.setattr("plugin._validate_pdf", lambda p: True)
    monkeypatch.setattr("plugin._rename_with_metadata", lambda paper, p: p)
    monkeypatch.setattr("plugin._extract_pdf_meta", lambda p: {"extracted_doi": ""})
    saved = _stub_host_artifact(monkeypatch)
    paper = {"doi": "10.1/x", "title": "T", "first_author": "A", "year": "2024"}

    record = _save_pdf(paper, b"%PDF-1.4\n%%EOF\nx", Path(tmp_path), "oa_direct")

    assert record is not None
    assert record["artifact_id"].startswith("sha256:")
    assert record["local_path"] == ""
    assert saved["filename"] == record["filename"]
    # 本地临时文件已清理（不留 PDF 副本在 workspace/papers）
    assert not list((Path(tmp_path) / "papers").glob("*.pdf"))


def test_save_pdf_returns_none_when_artifact_unavailable(tmp_path, monkeypatch):
    """宿主 artifact 能力不可用时明确降级：返回 None，不落本地文件。"""
    monkeypatch.setattr("plugin._validate_pdf", lambda p: True)
    monkeypatch.setattr("plugin._rename_with_metadata", lambda paper, p: p)
    monkeypatch.setattr("plugin._extract_pdf_meta", lambda p: {"extracted_doi": ""})
    monkeypatch.setattr(plugin, "_host_save_pdf", lambda *a, **k: None)
    paper = {"doi": "10.1/x", "title": "T", "first_author": "A", "year": "2024"}

    assert _save_pdf(paper, b"%PDF-1.4\n%%EOF\nx", Path(tmp_path), "oa_direct") is None
    assert not list((Path(tmp_path) / "papers").glob("*.pdf"))


def test_report_counts_unverified_separately(tmp_path):
    """报告口径：Success 只算已核验，未核验单列（否则"假成功"只是换了地方藏）。"""
    workspace = Path(tmp_path)
    results = [
        {"doi": "10.1/ok", "title": "ok", "verified": True, "local_path": "papers/ok.pdf"},
        {"doi": "10.1/un", "title": "un", "verified": False, "local_path": "papers/un.pdf"},
    ]

    _generate_report(workspace, results, [])

    reports = list((workspace / "reports").glob("download_report_*.csv"))
    assert reports, "报告应已生成"
    text = reports[0].read_text(encoding="utf-8-sig")
    assert "SUCCESS" in text and "UNVERIFIED" in text
    dashboard = list((workspace / "reports").glob("dashboard_*.html"))
    assert dashboard
    html = dashboard[0].read_text(encoding="utf-8")
    assert "Unverified" in html


def test_browser_route_removed_in_v090():
    """v0.9.0 反向断言：浏览器下载路径已移除（机构层明确降级）。"""
    assert not hasattr(plugin, "_browser_download")
    assert not hasattr(plugin, "_browser_capture_pdf")
    assert not hasattr(plugin, "_run_browser_attempt_isolated")
