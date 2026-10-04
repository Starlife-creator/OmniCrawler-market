from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("signal_sieve", ROOT / "plugin.py")
assert SPEC and SPEC.loader
plugin = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = plugin
SPEC.loader.exec_module(plugin)


HTML = """<html><head><title>Example</title><meta name='author' content='Ada'></head>
<body><nav><a href='/'>Home Products Contact</a></nav><article>
<h1>A useful heading for readers</h1><p>This is a substantial paragraph with enough useful words,
punctuation, and continuity to be treated as article content. It explains the important result.</p>
<p>A second paragraph provides supporting evidence and makes the extraction stable and useful.</p>
</article><footer>privacy terms sitemap</footer></body></html>"""


def test_extracts_article_and_metadata_without_navigation() -> None:
    result = plugin.extract_html(HTML, mode="balanced")
    assert result["ok"]
    assert result["title"] == "Example"
    assert result["author"] == "Ada"
    assert "substantial paragraph" in result["text"]
    assert "Home Products Contact" not in result["text"]
    assert result["diagnostics"]["accepted_blocks"] >= 1


def test_extractor_contract_shape() -> None:
    body = base64.b64encode(HTML.encode()).decode()
    output = plugin.handle("extractor.process", {"result": {"url": "https://example.test", "body_b64": body}})
    assert output["records"][0]["record_type"] == "clean_article"
    assert output["requests"] == []


def test_empty_html_explains_failure() -> None:
    result = plugin.extract_html("<nav>only navigation</nav>")
    assert not result["ok"]
    assert result["diagnostics"]["reason"] == "no_block_met_density_threshold"


def test_jsonld_metadata_and_boilerplate_penalty() -> None:
    source = """<html><head><script type="application/ld+json">
    {"@type":"NewsArticle","headline":"Structured title","author":{"name":"Lin"},
    "datePublished":"2026-08-31"}</script></head><body>
    <div class="sidebar-menu">This sidebar contains lots of repeated navigation words and links.</div>
    <article><p>This report contains enough meaningful prose, evidence, punctuation, and context
    to be selected as the primary article instead of the surrounding navigation chrome.</p></article>
    </body></html>"""
    result = plugin.extract_html(source, mode="recall")
    assert result["title"] == "Structured title"
    assert result["author"] == "Lin"
    assert result["published_at"] == "2026-08-31"
    assert "primary article" in result["text"]
    assert result["word_count"] > 10
