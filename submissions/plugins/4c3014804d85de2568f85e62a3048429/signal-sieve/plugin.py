"""Signal Sieve: explainable, dependency-free HTML main-text extraction."""

from __future__ import annotations

import base64
import html
import json
import re
from html.parser import HTMLParser
from typing import Any

PLUGIN_METADATA = {
    "name": "signal-sieve",
    "version": "0.2.0",
    "api_version": 1,
    "description": "融合文本密度、语义标签与 JSON-LD 提取正文、元数据和可解释诊断",
    "plugin_types": ["extractor", "transformer"],
    "category": "content-extraction",
    "tags": ["html", "article", "metadata", "explainable"],
    "permissions": [],
    "domains": [],
    "input_files": [],
    "dependencies": [],
    "license": "MIT",
    "execution_mode": "subprocess",
    "min_core_version": "0.11.2",
}

BLOCK_TAGS = {"article", "blockquote", "div", "h1", "h2", "h3", "li", "main", "p", "pre", "section"}
SKIP_TAGS = {"aside", "footer", "form", "nav", "noscript", "script", "style", "svg"}
SPACE = re.compile(r"\s+")
BOILERPLATE = re.compile(r"(?:nav|menu|footer|sidebar|cookie|banner|advert|share|related)", re.I)
MAX_JSONLD_CHARS = 256 * 1024


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.skip_depth = 0
        self.link_depth = 0
        self.current: list[str] = []
        self.current_links = 0
        self.current_tag = ""
        self.current_penalty = 0
        self.blocks: list[dict[str, Any]] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.metadata: dict[str, str] = {}
        self.in_jsonld = False
        self.jsonld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        self.stack.append(tag)
        if tag in SKIP_TAGS:
            self.skip_depth += 1
        if tag == "a":
            self.link_depth += 1
        if tag == "title":
            self.in_title = True
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        if tag == "script" and values.get("type", "").casefold() == "application/ld+json":
            self.in_jsonld = True
            self.jsonld_parts = []
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            content = values.get("content", "").strip()
            mapping = {
                "author": "author",
                "article:author": "author",
                "article:published_time": "published_at",
                "date": "published_at",
                "og:title": "title",
            }
            if key in mapping and content and mapping[key] not in self.metadata:
                self.metadata[mapping[key]] = content
        if tag in BLOCK_TAGS:
            self._flush()
            self.current_tag = tag
            marker = values.get("class", "") + " " + values.get("id", "")
            self.current_penalty = 80 if BOILERPLATE.search(marker) else 0

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in BLOCK_TAGS:
            self._flush()
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.in_jsonld:
            self._consume_jsonld("".join(self.jsonld_parts))
            self.in_jsonld = False
            self.jsonld_parts = []
        if tag == "a" and self.link_depth:
            self.link_depth -= 1
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        if self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.in_jsonld:
            used = sum(len(part) for part in self.jsonld_parts)
            if used < MAX_JSONLD_CHARS:
                self.jsonld_parts.append(data[: MAX_JSONLD_CHARS - used])
            return
        if self.skip_depth:
            return
        text = SPACE.sub(" ", html.unescape(data)).strip()
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        self.current.append(text)
        if self.link_depth:
            self.current_links += len(text)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = SPACE.sub(" ", " ".join(self.current)).strip()
        if text:
            length = len(text)
            link_ratio = self.current_links / max(length, 1)
            semantic = (
                28
                if self.current_tag in {"article", "main"}
                else 12
                if self.current_tag in {"p", "pre", "blockquote"}
                else 0
            )
            punctuation = min(24, sum(text.count(mark) for mark in ".!?。！？；;") * 3)
            score = (
                length
                + semantic
                + punctuation
                - round(link_ratio * length * 1.5)
                - self.current_penalty
            )
            self.blocks.append(
                {
                    "tag": self.current_tag or "text",
                    "text": text,
                    "score": score,
                    "link_ratio": round(link_ratio, 3),
                }
            )
        self.current = []
        self.current_links = 0
        self.current_tag = ""
        self.current_penalty = 0

    def _consume_jsonld(self, source: str) -> None:
        try:
            value = json.loads(source)
        except (json.JSONDecodeError, TypeError):
            return
        queue = value if isinstance(value, list) else [value]
        for item in queue[:20]:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph[:20])
            kind = str(item.get("@type", "")).casefold()
            if not any(token in kind for token in ("article", "posting", "report", "news")):
                continue
            author = item.get("author")
            if isinstance(author, dict):
                author = author.get("name")
            elif isinstance(author, list):
                author = ", ".join(
                    str(entry.get("name", "")) if isinstance(entry, dict) else str(entry)
                    for entry in author[:10]
                )
            mappings = {
                "title": item.get("headline") or item.get("name"),
                "author": author,
                "published_at": item.get("datePublished"),
            }
            for key, raw in mappings.items():
                text = SPACE.sub(" ", str(raw or "")).strip()
                if text and key not in self.metadata:
                    self.metadata[key] = text[:500]


def extract_html(source: str, *, mode: str = "balanced") -> dict[str, Any]:
    parser = _Extractor()
    parser.feed(source)
    parser.close()
    thresholds = {"precision": 100, "balanced": 45, "recall": 20}
    effective_mode = mode if mode in thresholds else "balanced"
    accepted = [
        block
        for block in parser.blocks
        if block["score"] >= thresholds[effective_mode] and block["link_ratio"] <= 0.55
    ]
    unique = []
    seen = set()
    for block in accepted:
        signature = SPACE.sub(" ", block["text"]).casefold()
        if signature not in seen:
            seen.add(signature)
            unique.append(block)
    fallback_used = False
    if not unique and parser.blocks:
        candidate = max(parser.blocks, key=lambda item: item["score"])
        if len(candidate["text"]) >= 80 and candidate["link_ratio"] <= 0.65:
            unique = [candidate]
            fallback_used = True
    text = "\n\n".join(block["text"] for block in unique)
    title = parser.metadata.get("title") or SPACE.sub(" ", " ".join(parser.title_parts)).strip()
    confidence = min(1.0, len(text) / 1200 + len(unique) / 20) if text else 0.0
    if fallback_used:
        confidence = min(confidence, 0.45)
    cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
    language = "zh" if text and cjk / len(text) > 0.15 else "und"
    word_count = cjk + len(re.findall(r"\b[\w'-]+\b", text))
    return {
        "ok": bool(text),
        "title": title,
        "author": parser.metadata.get("author", ""),
        "published_at": parser.metadata.get("published_at", ""),
        "text": text,
        "markdown": "\n\n".join(
            ("# " + block["text"] if block["tag"] == "h1" else "## " + block["text"] if block["tag"] in {"h2", "h3"} else block["text"])
            for block in unique
        ),
        "language": language,
        "word_count": word_count,
        "reading_time_minutes": round(word_count / 220, 1) if word_count else 0.0,
        "confidence": round(confidence, 3),
        "diagnostics": {
            "mode": effective_mode,
            "candidate_blocks": len(parser.blocks),
            "accepted_blocks": len(unique),
            "rejected_blocks": len(parser.blocks) - len(unique),
            "fallback_used": fallback_used,
            "reason": "" if text else "no_block_met_density_threshold",
            "top_candidates": sorted(parser.blocks, key=lambda item: item["score"], reverse=True)[:5],
        },
    }


def _html_from_result(result: dict[str, Any]) -> str:
    body = result.get("body_b64")
    if not body:
        return ""
    try:
        return base64.b64decode(str(body), validate=True).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def handle(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    options = dict(payload.get("options") or {})
    if operation == "extractor.process":
        result = dict(payload.get("result") or {})
        extracted = extract_html(_html_from_result(result), mode=str(options.get("mode", "balanced")))
        return {
            "records": [
                {
                    "source_url": str(result.get("url") or ""),
                    "record_type": "clean_article",
                    "data": extracted,
                    "evidence": {"method": "signal-sieve-v1", "confidence": extracted["confidence"]},
                }
            ]
            if extracted["ok"]
            else [],
            "requests": [],
            "artifact_path": None,
        }
    if operation == "transformer.transform":
        record = dict(payload.get("record") or {})
        data = dict(record.get("data") or {})
        source = str(data.get("html") or data.get("body") or "")
        return {
            "data": {**data, "extracted": extract_html(source, mode=str(options.get("mode", "balanced")))}
        }
    return {}
