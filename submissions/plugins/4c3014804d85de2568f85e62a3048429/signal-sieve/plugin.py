"""Signal Sieve: explainable, dependency-free HTML main-text extraction."""

from __future__ import annotations

import base64
import html
import json
import re
from html.parser import HTMLParser
from collections import deque
from typing import Any

PLUGIN_METADATA = {
    "name": "signal-sieve",
    "version": "0.4.0",
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
        self.stack: list[tuple[str, bool, bool]] = []
        self.jsonld_size = 0
        self.skip_depth = 0
        self.link_depth = 0
        self.current: list[str] = []
        self.current_links = 0
        self.current_tag = ""
        self.current_penalty = 0
        self.current_semantic = False
        self.blocks: list[dict[str, Any]] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.metadata: dict[str, str] = {}
        self.in_jsonld = False
        self.jsonld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        marker = values.get("class", "") + " " + values.get("id", "")
        parent_noise = any(frame[1] for frame in self.stack)
        semantic = tag in {"article", "main"} or any(frame[2] for frame in self.stack)
        noise = parent_noise or bool(BOILERPLATE.search(marker))
        # Void elements never acquire ancestry or skip state.
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, noise, semantic))
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
            self.jsonld_size = 0
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
            self.current_penalty = 1000000 if noise else 0
            self.current_semantic = semantic

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
        matching = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if matching is not None:
            del self.stack[matching:]
        self.skip_depth = sum(frame[0] in SKIP_TAGS for frame in self.stack)
        self.link_depth = sum(frame[0] == "a" for frame in self.stack)

    def handle_data(self, data: str) -> None:
        if self.in_jsonld:
            used = self.jsonld_size
            if used < MAX_JSONLD_CHARS:
                part = data[: MAX_JSONLD_CHARS - used]
                self.jsonld_parts.append(part)
                self.jsonld_size += len(part)
            return
        if self.skip_depth:
            return
        text = SPACE.sub(" ", html.unescape(data)).strip()
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
            return
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
                if getattr(self, "current_semantic", False)
                else 12
                if self.current_tag in {"p", "pre", "blockquote"}
                else 0
            )
            punctuation = min(24, sum(text.count(mark) for mark in ".!?。！？；;") * 3)
            tokens = re.findall(r"[\w'-]+", text.casefold())
            repetitive = (not getattr(self, "current_semantic", False) and self.current_tag not in {"p", "pre", "blockquote"}
                          and len(tokens) >= 100 and len(set(tokens)) / len(tokens) < 0.03 and punctuation == 0)
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
                    "noise": bool(self.current_penalty) or repetitive,
                    "repetitive": repetitive,
                    "semantic": bool(getattr(self, "current_semantic", False)),
                }
            )
        self.current = []
        self.current_links = 0
        self.current_tag = ""
        self.current_penalty = 0
        self.current_semantic = False

    def _consume_jsonld(self, source: str) -> None:
        try:
            value = json.loads(source)
        except (json.JSONDecodeError, TypeError):
            return
        queue = deque(value[:20] if isinstance(value, list) else [value])
        visited = 0
        while queue and visited < 100:
            item = queue.popleft()
            visited += 1
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
        if not block["noise"] and block["score"] >= thresholds[effective_mode] and block["link_ratio"] <= 0.55
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
        candidate = max((b for b in parser.blocks if not b["noise"]), key=lambda item: item["score"], default={"text": "", "link_ratio": 1})
        if len(candidate["text"]) >= 80 and candidate["link_ratio"] <= 0.65:
            unique = [candidate]
            fallback_used = True
    text = "\n\n".join(block["text"] for block in unique)
    title = parser.metadata.get("title") or SPACE.sub(" ", " ".join(parser.title_parts)).strip()
    # A quality heuristic, never a probability: length alone cannot imply quality.
    length = max(1, sum(len(b["text"]) for b in unique))
    structured = sum(len(b["text"]) for b in unique if b.get("semantic") or b["tag"] in {"p", "pre", "blockquote"}) / length
    link_clean = 1 - sum(len(b["text"]) * b["link_ratio"] for b in unique) / length
    punctuation = min(1.0, sum(text.count(c) for c in ".!?。！？；;") / max(1, len(text) / 100))
    tokens = re.findall(r"[\w'-]+", text.casefold())
    diversity = len(set(tokens)) / max(1, len(tokens))
    confidence = (0.35 * structured + 0.25 * punctuation + 0.2 * link_clean + 0.2 * min(1, len(text) / 600)) if text else 0.0
    if not structured or (len(tokens) > 30 and diversity < 0.08):
        confidence = min(confidence, 0.45)
    if fallback_used:
        confidence = min(confidence, 0.45)
    cjk = sum("\u3400" <= char <= "\u9fff" for char in text)
    language = "zh" if text and cjk / len(text) > 0.15 else "und"
    word_count = cjk + len(re.findall(r"\b[\w'-]+\b", re.sub(r"[\u3400-\u9fff]", " ", text)))
    return {
        "ok": bool(text),
        "title": title,
        "author": parser.metadata.get("author", ""),
        "published_at": parser.metadata.get("published_at", ""),
        "text": text,
        "markdown": "\n\n".join(
            ("# " + block["text"] if block["tag"] == "h1" else "## " + block["text"] if block["tag"] in {"h2", "h3"} else "- " + block["text"] if block["tag"] == "li" else "```\n" + block["text"] + "\n```" if block["tag"] == "pre" else "> " + block["text"] if block["tag"] == "blockquote" else block["text"])
            for block in unique
        ),
        "language": language,
        "word_count": word_count,
        "reading_time_minutes": round(word_count / 220, 1) if word_count else 0.0,
        "confidence": round(confidence, 3),
        "quality": "high" if confidence >= 0.75 else "usable" if confidence >= 0.45 else "low",
        "diagnostics": {
            "mode": effective_mode,
            "candidate_blocks": len(parser.blocks),
            "accepted_blocks": len(unique),
            "rejected_blocks": len(parser.blocks) - len(unique),
            "fallback_used": fallback_used,
            "score_kind": "heuristic_quality_not_probability",
            "structured_ratio": round(structured, 3),
            "link_clean_ratio": round(link_clean, 3),
            "punctuation_density": round(punctuation, 3),
            "reason": "" if text else "no_block_met_density_threshold",
            "top_candidates": sorted(parser.blocks, key=lambda item: item["score"], reverse=True)[:5],
        },
    }


def _html_from_result(result: dict[str, Any]) -> str:
    body = result.get("body_b64")
    if not body:
        return ""
    try:
        raw = base64.b64decode(str(body), validate=True)
        headers = result.get("headers") or {}
        content_type = str(result.get("content_type") or next((v for k, v in headers.items() if str(k).lower() == "content-type"), "")) if isinstance(headers, dict) else ""
        match = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type, re.I)
        declared = match.group(1) if match else ""
        if not declared:
            match = re.search(rb"charset\s*=\s*['\"]?([\w-]+)", raw[:4096], re.I)
            declared = match.group(1).decode("ascii") if match else ""
        encodings = (["utf-16"] if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else []) + [declared, "utf-8-sig", "gb18030", "windows-1252"]
        for encoding in encodings:
            if not encoding:
                continue
            try:
                return raw.decode(encoding)
            except (UnicodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")
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
                    "source_url": str(result.get("final_url") or result.get("url") or (result.get("request") or {}).get("url") or ""),
                    "record_type": "clean_article",
                    "data": extracted,
                    "evidence": {"method": "signal-sieve-v1", "confidence": extracted["confidence"]},
                }
            ]
            if extracted["ok"]
            else ([{"source_url": str(result.get("final_url") or result.get("url") or (result.get("request") or {}).get("url") or ""),
                    "record_type": "extraction_diagnostic", "data": extracted["diagnostics"],
                    "evidence": {"method": "signal-sieve-v2", "confidence": 0.0}}]
                  if options.get("emit_diagnostics") else []),
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
