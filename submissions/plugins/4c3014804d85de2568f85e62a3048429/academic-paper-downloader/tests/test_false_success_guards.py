"""「假成功」防护测试（issue #22 §1）。

锁定的性质：
- 反爬挑战页/登录页**根本不会被存成 PDF**（`page.pdf()` 都不许调用）；
- 文章落地页（拿不到"这是 PDF"的证据）也不许打印成 PDF；
- 反过来，**真正的内联 PDF 视图**必须仍然能打印（否则守卫退化成"一律拒绝"）；
- PDF 内提不出 DOI ⇒ 文件**保留**但标记 `verified=False`，**不计入成功**；
- 报告与 hook 返回值按同一口径计数（Success 不含未核验）。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plugin  # noqa: E402
from plugin import (  # noqa: E402
    _browser_capture_pdf,
    _browser_download,
    _generate_report,
    _save_pdf,
)


class _FakePage:
    """记录 `page.pdf()` 是否被调用 —— 挑战页必须一次都不调用。"""

    def __init__(self, *, title="", body="", url="https://example.com/article", pdf_value=b"%PDF-1.4\n" + b"x" * 2000):
        self._title = title
        self._body = body
        self.url = url
        self._pdf_value = pdf_value
        self.pdf_calls = 0

    def title(self):
        return self._title

    def inner_text(self, _selector):
        return self._body

    def query_selector(self, _selector):
        return None

    def pdf(self):
        self.pdf_calls += 1
        return self._pdf_value


class _FakeContext:
    def expect_page(self, **_kwargs):
        raise RuntimeError("no popup")


def _save(tmp_path, monkeypatch, *, extracted_meta):
    monkeypatch.setattr("plugin._validate_pdf", lambda p: True)
    monkeypatch.setattr("plugin._rename_with_metadata", lambda paper, p: p)
    monkeypatch.setattr("plugin._extract_pdf_meta", lambda p: extracted_meta)
    paper = {"doi": "10.1038/s41586-021-00001-2", "title": "T", "first_author": "A", "year": "2021"}
    return _save_pdf(paper, b"%PDF-1.4\n%%EOF\nx", Path(tmp_path), "browser")


# --- 页面级守卫 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "page_kwargs",
    [
        {"title": "Just a moment...", "body": "checking your browser"},
        {"title": "", "body": "onlinelibrary.wiley.com Performing security verification"},
        {"title": "Access Denied", "body": "you are a robot"},
        {"title": "Sign in", "body": "institutional login required"},
    ],
)
def test_challenge_or_login_page_is_never_saved(page_kwargs, tmp_path, monkeypatch):
    """挑战页/登录页/拒绝页：直接放弃，**且一次都不调用 page.pdf()**。"""
    monkeypatch.setattr(plugin.tempfile, "NamedTemporaryFile", lambda **k: (_ for _ in ()).throw(AssertionError("不应落盘")))
    page = _FakePage(**page_kwargs)

    assert _browser_capture_pdf(_FakeContext(), page) is None
    assert page.pdf_calls == 0


def test_landing_page_without_pdf_evidence_is_not_printed(tmp_path):
    """文章落地页（非挑战页，但页面不是 PDF 视图）不许打印成 PDF。"""
    page = _FakePage(title="Article title", body="Abstract ...", url="https://publisher.example/article/1")

    assert _browser_capture_pdf(_FakeContext(), page) is None
    assert page.pdf_calls == 0  # 守卫没有退化成"一律打印"


def test_inline_pdf_view_is_still_printed(tmp_path):
    """正向对照：真正的 PDF 视图必须仍能兜底（否则守卫等于把能力关掉）。"""
    page = _FakePage(title="paper", body="", url="https://publisher.example/article.pdf")

    result = _browser_capture_pdf(_FakeContext(), page)

    assert page.pdf_calls == 1
    assert result is not None and Path(result).is_file()
    Path(result).unlink()


# --- DOI 核验：未核验保留但不计入成功 ----------------------------------------


def test_unverifiable_pdf_is_kept_but_marked_unverified(tmp_path, monkeypatch):
    record = _save(tmp_path, monkeypatch, extracted_meta={})

    assert record is not None, "arXiv/扫描版 PDF 本就提不出 DOI，不能误拒"
    assert record["verified"] is False
    assert record["verification"] == "doi_not_found_in_pdf"
    assert list((Path(tmp_path) / "papers").glob("*.pdf")), "文件保留"


def test_matched_doi_is_marked_verified(tmp_path, monkeypatch):
    record = _save(tmp_path, monkeypatch, extracted_meta={"extracted_doi": "10.1038/S41586-021-00001-2."})

    assert record is not None
    assert record["verified"] is True
    assert record["verification"] == "doi_matched"


def test_mismatched_doi_is_still_rejected(tmp_path, monkeypatch):
    record = _save(tmp_path, monkeypatch, extracted_meta={"extracted_doi": "10.9999/other"})

    assert record is None
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


def test_unknown_publisher_uses_generic_route(monkeypatch):
    """未知出版商不再直接放弃：仍走一次通用浏览器路径（doi.org → 实际文章页）。"""
    calls = []

    def fake_attempt(doi, publisher, home, cookies, config, *, headless):
        calls.append((doi, home, headless))
        return "/tmp/x.pdf"

    monkeypatch.setattr(plugin, "_browser_attempt", fake_attempt)

    assert _browser_download("10.9999/unknown.1", "not-in-table", [], {}) == "/tmp/x.pdf"
    assert calls and calls[0][1] == "https://doi.org"


def test_headless_is_configurable_and_visible_retry_happens(monkeypatch):
    """headless 可配；headless 失败且允许时用可见浏览器重试一次。"""
    seen = []

    def fake_attempt(doi, publisher, home, cookies, config, *, headless):
        seen.append(headless)
        return None if len(seen) == 1 else "/tmp/y.pdf"

    monkeypatch.setattr(plugin, "_browser_attempt", fake_attempt)
    cfg = {"institution": {"headless": True, "visible_fallback": True}}

    assert _browser_download("10.1016/j.x.2023.1", "elsevier", [], cfg) == "/tmp/y.pdf"
    assert seen == [True, False]


def test_headless_false_does_not_retry(monkeypatch):
    seen = []
    monkeypatch.setattr(
        plugin,
        "_browser_attempt",
        lambda doi, publisher, home, cookies, config, *, headless: seen.append(headless) or None,
    )

    assert _browser_download("10.1016/j.x.2023.1", "elsevier", [], {"institution": {"headless": False}}) is None
    assert seen == [False]
