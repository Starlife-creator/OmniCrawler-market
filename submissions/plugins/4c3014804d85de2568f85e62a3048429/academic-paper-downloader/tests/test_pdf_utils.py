"""PDF 校验与文件名去重测试。"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _unique_filename, _validate_pdf, _extract_pdf_meta, _save_pdf


class TestFilenameDedup:
    def test_unique_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers_dir = Path(tmp)
            result = _unique_filename(papers_dir, "test.pdf")
            assert result.name == "test.pdf"

    def test_duplicate_adds_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers_dir = Path(tmp)
            (papers_dir / "test.pdf").write_text("x")
            result = _unique_filename(papers_dir, "test.pdf")
            assert result.name == "test_1.pdf"

    def test_multiple_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            papers_dir = Path(tmp)
            (papers_dir / "test.pdf").write_text("x")
            (papers_dir / "test_1.pdf").write_text("x")
            (papers_dir / "test_2.pdf").write_text("x")
            result = _unique_filename(papers_dir, "test.pdf")
            assert result.name == "test_3.pdf"


class TestPdfValidation:
    def test_validate_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"not a pdf")
            path = Path(f.name)
        try:
            assert _validate_pdf(path) is False
        finally:
            path.unlink(missing_ok=True)

    def test_validate_fallback_magic_bytes(self, monkeypatch, tmp_path):
        """PDF 解析库都不可用时，退化为 %PDF 魔数校验，不丢弃已下载文件。"""
        monkeypatch.setitem(sys.modules, "pdfplumber", None)
        monkeypatch.setitem(sys.modules, "pypdf", None)

        ok = tmp_path / "ok.pdf"
        ok.write_bytes(b"%PDF-1.4\n%%EOF\n")
        assert _validate_pdf(ok) is True

        bad = tmp_path / "bad.bin"
        bad.write_bytes(b"<html>not a pdf</html>")
        assert _validate_pdf(bad) is False

    def test_extract_meta_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4\n%EOF\n")
            path = Path(f.name)
        try:
            meta = _extract_pdf_meta(path)
            assert isinstance(meta, dict)
        finally:
            path.unlink(missing_ok=True)


class TestPdfDoiCrossCheck:
    def test_mismatched_doi_kept_as_unverified(self, monkeypatch, tmp_path):
        """v0.6.3 实机修正：DOI 提取抽错的 PDF 保留为 UNVERIFIED（不计成功），
        不再删除——实机发现过验证拿到的文件可能因提取排版误判而被白删。"""
        monkeypatch.setattr("plugin._validate_pdf", lambda p: True)
        monkeypatch.setattr("plugin._rename_with_metadata", lambda paper, p: p)
        monkeypatch.setattr("plugin._extract_pdf_meta",
                            lambda p: {"extracted_doi": "10.9999/Different.1"})
        paper = {"doi": "10.1007/s40468-024-99999-9", "title": "T", "first_author": "A", "year": "2025"}
        record = _save_pdf(paper, b"%PDF-1.4\n%%EOF\nx", Path(tmp_path), "browser")
        assert record is not None
        assert record["verified"] is False
        assert list((Path(tmp_path) / "papers").glob("*.pdf"))  # 文件保留供人工确认

    def test_matched_doi_accepted(self, monkeypatch, tmp_path):
        """提取 DOI 与请求一致（忽略大小写/末尾点）→ 正常保存。"""
        monkeypatch.setattr("plugin._validate_pdf", lambda p: True)
        monkeypatch.setattr("plugin._rename_with_metadata", lambda paper, p: p)
        monkeypatch.setattr("plugin._extract_pdf_meta",
                            lambda p: {"extracted_doi": "10.1007/s40468-024-99999-9."})
        paper = {"doi": "10.1007/S40468-024-99999-9", "title": "T", "first_author": "A", "year": "2025"}
        record = _save_pdf(paper, b"%PDF-1.4\n%%EOF\nx", Path(tmp_path), "browser")
        assert record is not None and record["doi"] == "10.1007/S40468-024-99999-9"

    def test_no_extracted_doi_accepted(self, monkeypatch, tmp_path):
        """PDF 无法提取 DOI（如 arXiv 无码文献）→ 不误拒。"""
        monkeypatch.setattr("plugin._validate_pdf", lambda p: True)
        monkeypatch.setattr("plugin._rename_with_metadata", lambda paper, p: p)
        monkeypatch.setattr("plugin._extract_pdf_meta", lambda p: {})
        paper = {"doi": "10.48550/arXiv.2101.00001", "title": "T", "first_author": "A", "year": "2021"}
        record = _save_pdf(paper, b"%PDF-1.4\n%%EOF\nx", Path(tmp_path), "oa_direct")
        assert record is not None and record["doi"] == "10.48550/arXiv.2101.00001"
