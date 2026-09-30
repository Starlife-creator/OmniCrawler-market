#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Web 发现页生成器（§10.12）：fail-closed 验签 catalog ⇒ 渲染三级静态站。

★ 安全与语义边界（§10.12 硬性要求）：
- **先验签后渲染**：catalog.json 必须被 catalog.json.sig 覆盖（信任根公钥校验），
  验签失败 ⇒ 拒绝生成（退出码 1）——被篡改的目录永远上不了 Pages。
- **渲染语义与客户端一致（M5）**：官方＝publisher 命中 official_publishers；
  已审核＝维护者复签文件存在；**权限风险分级与高权限判定 = 客户端同一判据**
  （`omnicrawler/gui/views/plugin_market_logic.py::_permission_risk` / `_badges`）
  —— 站点与客户端不得各说一套。
- **站点不做验签结论**（§10.12.5）：页面只**陈述生成方式**，不出现「已通过验签」式结论，
  也不提供安装动作；安装与最终验签在客户端完成，文案沿用客户端的安装须知口径。
- **目录字段一律 HTML 转义**（含 `listing.md`）：签名只证明「这些字节被认领」，
  不证明「这些字节是安全 HTML」。
- **页面零外部子资源**：样式、脚本、字标全部内联；图标/og/manifest 由构建期从主仓
  `assets/branding/web/` 取用并**复制进产物**（不落仓，见 §10.12.3 #4）。
  页面加载不向任何第三方发起请求；正文外链只在用户主动点击时离开本站。

★ 输出结构（§10.12.4：首页 → 列表页 → 详情页）：
    index.html                     首页（定位 / 统计 / 分类入口 / 最近更新）
    catalog.html                   列表页（搜索 + 多维筛选 + 卡片）
    <id>.html                      详情页（id 含层级时落子目录，如 cms/market/x.html）

用法：python tools/generate_discovery_page.py [--output _pages] [--web-assets <主仓 web 资产目录>]
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
from pathlib import Path

_REGISTRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REGISTRY / "tools"))

from catalog_lib.signing import _verify_catalog_signature  # noqa: E402

# 站内到仓库文件的链接、站点地址回落值（CI 里由 GITHUB_REPOSITORY 覆盖）
_FALLBACK_REPO = "Starlife-creator/OmniCrawler-market"
_SIG_NAME = "catalog.json.sig"
_INDEX = "index.html"
_LIST = "catalog.html"
_LOGO_DIR = Path("assets") / "branding" / "lockup"
_FACTS_LIMIT = 12

# 主仓站点资产（§10.12.3 #4：不搬家、构建期取用、不落仓）。
# `html-head-snippet.html` 属于「粘贴用片段」，本站已把它**消费**进每个页面的 <head>
# ⇒ 复制清单里不含它（避免站点根上多出一个会误导人手改的文件）。
_WEB_ASSET_FILES = (
    "favicon.ico",
    "favicon-16x16.png",
    "favicon-32x32.png",
    "favicon-48x48.png",
    "apple-touch-icon.png",
    "android-chrome-192x192.png",
    "android-chrome-512x512.png",
    "maskable-512.png",
    "og-image.png",
    "og-image.svg",
    "site.webmanifest",
)
_WEB_SNIPPET = "html-head-snippet.html"

# 客户端 `_permission_risk` 的两个集合（判据唯一真源在客户端；这里镜像，改动须两边同批）
_HIGH_RISK_PERMISSIONS = {"secrets:read", "responses:payload", "render:scripted"}
_MEDIUM_RISK_PERMISSIONS = {
    "network:scoped",
    "records:write",
    "responses:read",
    "artifacts:write",
    "files:read",
    "temp:write",
    "resources:read",
    "surfaces:background",
    "render:local",
}

_ID_RE = re.compile(r"^[a-z][a-z0-9_/-]*$")  # 与 catalog_lib.schema 的 id 约束同域


# --------------------------------------------------------------------------- 基础工具

def _esc(value: object) -> str:
    """把任意目录字段转成安全的 HTML 文本（含引号，可安全用于属性值）。"""
    return html.escape(str(value if value is not None else ""), quote=True)


def _text(value: object) -> str:
    """把结构化的目录字段压成单行文本（依赖列表等）。"""
    if isinstance(value, dict):
        parts = [str(value.get("name") or value.get("id") or "").strip()]
        if value.get("version"):
            parts.append(str(value["version"]))
        if value.get("license"):
            parts.append(f"({value['license']})")
        joined = " ".join(p for p in parts if p)
        return joined or json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, (list, tuple)):
        return " ".join(_text(item) for item in value)
    return str(value)


def _pairs(value: object) -> list[str]:
    """把 dict 形式的字段渲染成 ["键 值", ...]（需求能力/依赖）。"""
    if isinstance(value, dict):
        return [f"{key} {val}" for key, val in value.items()]
    if isinstance(value, (list, tuple)):
        return [
            f"{item.get('name', '')} {item.get('version', '')}".strip() if isinstance(item, dict) else str(item)
            for item in value
        ]
    return []


def _chips(items: list[object], cls: str = "chip", kind: str = "") -> str:
    """渲染一组 chip；超量时折叠计数，避免长列表撑爆卡片。"""
    values = [_text(item).strip() for item in items]
    values = [v for v in values if v]
    if not values:
        return ""
    classes = f"{cls} {cls}-{kind}" if kind else cls
    head, rest = values[:_FACTS_LIMIT], values[_FACTS_LIMIT:]
    out = "".join(f'<span class="{classes}">{_esc(v)}</span>' for v in head)
    if rest:
        out += f'<span class="{classes}" title="{_esc("、".join(rest))}">…等 {len(values)} 项</span>'
    return out


def _facts(rows: list[tuple[str, str]]) -> str:
    """渲染 <dt>/<dd> 事实表；值为空的行自动跳过。"""
    body = "".join(f"<dt>{_esc(label)}</dt><dd>{value}</dd>" for label, value in rows if value)
    return f'<dl class="facts">{body}</dl>' if body else ""


def _version_key(version: object) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(version)))


def _repo_link(repo: str, path: str, label: str) -> str:
    """指向仓库内某个文件的链接（路径按段转义，防目录内容构造出站外链接）。"""
    if not repo or not path:
        return ""
    quoted = "/".join(_esc(segment) for segment in str(path).strip("/").split("/"))
    return f'<a href="https://github.com/{_esc(repo)}/blob/main/{quoted}">{_esc(label)}</a>'


def _search_blob(*values: object) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            parts.extend(_text(item) for item in value)
        elif isinstance(value, dict):
            parts.append(_text(value))
        elif value is not None:
            parts.append(str(value))
    return _esc(" ".join(part for part in parts if part).casefold())


# ------------------------------------------------------------------- M5 语义（镜像客户端）

def _permission_risk(entry: dict) -> tuple[str, str]:
    """权限风险分级（与客户端 `plugin_market_logic._permission_risk` 同一判据）。"""
    permissions = {str(item).strip().casefold() for item in (entry.get("permissions") or []) if str(item).strip()}
    if str(entry.get("execution_mode") or "subprocess") == "in_process" or permissions & _HIGH_RISK_PERMISSIONS:
        return "high", "高风险"
    if permissions & _MEDIUM_RISK_PERMISSIONS:
        return "medium", "需授权"
    return "low", "低风险"


def _risk_reason(entry: dict) -> str:
    level, _label = _permission_risk(entry)
    if level == "high":
        if str(entry.get("execution_mode") or "subprocess") == "in_process":
            return "执行模式为 in_process（进程内运行）"
        hit = sorted({str(p) for p in (entry.get("permissions") or [])} & _HIGH_RISK_PERMISSIONS)
        return "请求了高权限：" + "、".join(hit)
    if level == "medium":
        hit = sorted({str(p) for p in (entry.get("permissions") or [])} & _MEDIUM_RISK_PERMISSIONS)
        return "请求了需授权权限：" + "、".join(hit) if hit else "请求了需授权权限"
    return "未请求网络/写入/密钥类权限"


def _reviewed(entry: dict) -> bool:
    """已审核＝维护者复签文件存在（M5：已审核＝流程状态）。"""
    return bool(str(entry.get("maintainer_package_signature_file") or "").strip())


def _official(entry: dict, official: set[str]) -> bool:
    publisher = str(entry.get("publisher") or "").strip().casefold()
    return bool(publisher) and publisher in official


def _badges(entry: dict, official: set[str]) -> str:
    """徽章（M5：官方＝作者身份、已审核＝流程状态、高权限＝权限风险，三者非互斥）。"""
    badges = []
    if _official(entry, official):
        badges.append('<span class="b b-official">官方</span>')
    if _reviewed(entry):
        badges.append('<span class="b b-reviewed">已审核</span>')
    if _permission_risk(entry)[0] == "high":
        badges.append('<span class="b b-high">高权限</span>')
    publisher = str(entry.get("publisher") or "")
    badges.append(f'<span class="b b-pub">{_esc(publisher or "—")}</span>')
    return " ".join(badges)


# --------------------------------------------------------------------- 极简 Markdown 渲染

_FENCE_RE = re.compile(r"^```([A-Za-z0-9_+-]*)\s*$")
_TABLE_SEP_RE = re.compile(r"^[\s:-]*-[\s:|-]*$")
_LINK_INLINE_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_SAFE_URL_RE = re.compile(r"^(?:https?://|mailto:)", re.IGNORECASE)


def _md_inline(text: str) -> str:
    """行内格式：**粗** / *斜* / `代码` / [文字](链接)。输入必须是**已转义**文本。

    ★ 只认 http(s)/mailto 链接（其余原样呈现为文字），因此 `javascript:` 之类
    构造不出可点击链接；图片 `![]()` 一律不渲染（保持零外部请求）。
    """
    out = _LINK_INLINE_RE.sub(
        lambda m: (
            f'<a href="{m.group(2)}" rel="noopener noreferrer">{m.group(1)}</a>'
            if _SAFE_URL_RE.match(m.group(2))
            else m.group(0)
        ),
        text,
    )
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", out)
    return out


def _is_block_start(lines: list[str], index: int) -> bool:
    stripped = lines[index].strip()
    if _FENCE_RE.match(stripped) or re.match(r"^#{1,6}\s", stripped) or re.match(r"^[-*+]\s", stripped):
        return True
    if re.match(r"^\d+\.\s", stripped) or stripped.startswith("&gt;") or stripped in {"---", "***", "___"}:
        return True
    if stripped.startswith("|") and index + 1 < len(lines):
        return bool(_TABLE_SEP_RE.match(lines[index + 1].strip().lstrip("|")))
    return False


def markdown_to_html(source: str) -> str:
    """把 listing.md 渲染成受限 HTML（**转义优先**，只认白名单构造）。

    支持：标题（降一级，避免与页面 h1 冲突）、段落、有序/无序列表、代码围栏、
    表格、引用、分隔线、行内代码/粗斜体/链接。段落内换行**保留为 `<br>`**
    （投稿文档多为手写排版，硬换行是作者意图，不按 CommonMark 折成一行）。
    """
    lines = _esc(source or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        fence = _FENCE_RE.match(stripped)
        if fence:
            i += 1
            body: list[str] = []
            while i < len(lines) and not _FENCE_RE.match(lines[i].strip()):
                body.append(lines[i])
                i += 1
            i += 1  # 吃掉收尾围栏（缺失时越界即结束）
            lang = f' data-lang="{fence.group(1)}"' if fence.group(1) else ""
            out.append(f'<pre class="code"{lang}><code>{chr(10).join(body)}</code></pre>')
            continue

        if not stripped:
            i += 1
            continue

        if re.match(r"^#{1,6}\s", stripped):
            level = min(len(stripped) - len(stripped.lstrip("#")) + 1, 6)
            out.append(f"<h{level}>{_md_inline(stripped[level - 1:].strip())}</h{level}>")
            i += 1
            continue

        if stripped in {"---", "***", "___"}:
            out.append("<hr>")
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1].strip().lstrip("|")):
            header = [cell.strip() for cell in stripped.strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([cell.strip() for cell in lines[i].strip().strip("|").split("|")])
                i += 1
            head_html = "".join(f"<th>{_md_inline(cell)}</th>" for cell in header)
            body_html = "".join(
                "<tr>" + "".join(f"<td>{_md_inline(cell)}</td>" for cell in row) + "</tr>" for row in rows
            )
            out.append(
                f'<div class="table-wrap"><table><thead><tr>{head_html}</tr></thead>'
                f"<tbody>{body_html}</tbody></table></div>"
            )
            continue

        if re.match(r"^[-*+]\s", stripped):
            items: list[str] = []
            while i < len(lines) and re.match(r"^[-*+]\s", lines[i].strip()):
                items.append(_md_inline(lines[i].strip()[2:].strip()))
                i += 1
            out.append("<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>")
            continue

        if re.match(r"^\d+\.\s", stripped):
            ordered: list[str] = []
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i].strip()):
                ordered.append(_md_inline(re.sub(r"^\d+\.\s", "", lines[i].strip())))
                i += 1
            out.append("<ol>" + "".join(f"<li>{item}</li>" for item in ordered) + "</ol>")
            continue

        if stripped.startswith("&gt;"):
            quoted: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("&gt;"):
                quoted.append(_md_inline(lines[i].strip()[4:].strip()))
                i += 1
            out.append("<blockquote>" + "<br>".join(quoted) + "</blockquote>")
            continue

        paragraph: list[str] = []
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines, i):
            paragraph.append(_md_inline(lines[i].strip()))
            i += 1
        out.append("<p>" + "<br>".join(paragraph) + "</p>")
    return "\n".join(out)


# ---------------------------------------------------------------------------- 页面骨架

def _inline_logo(assets_root: Path) -> str:
    """内联品牌字标（浅/深两版，随 prefers-color-scheme 切换），保持零外部请求。"""
    variants = []
    for cls, filename in (("wm-light", "omnicrawler-wordmark.svg"), ("wm-dark", "omnicrawler-wordmark-dark.svg")):
        path = assets_root / _LOGO_DIR / filename
        if not path.is_file():
            continue
        svg = path.read_text(encoding="utf-8")
        svg = re.sub(r"<title\b[^>]*>.*?</title>", "", svg, flags=re.S)
        svg = re.sub(r"<desc\b[^>]*>.*?</desc>", "", svg, flags=re.S)
        # 去掉 role/aria-*/id：字标是装饰性的（标题已给出页面名），且两份内联会撞 id
        svg = re.sub(r'\s(?:role|aria-labelledby|aria-describedby|id)="[^"]*"', "", svg)
        svg = svg.replace("<svg ", f'<svg class="{cls}" aria-hidden="true" focusable="false" ', 1)
        variants.append(svg.strip())
    if not variants:
        return ""
    return '<div class="logo" aria-hidden="true">' + "".join(variants) + "</div>"


def _rel_prefix(path: str) -> str:
    """页面深度对应的相对前缀（详情页落在子目录里时才能链对同级页面）。"""
    return "../" * path.count("/")


def _site_root(repo: str, site_url: str | None = None) -> str:
    """站点根 URL。Pages 的 host 恒为小写（`<owner>.github.io`），仓库名保留原样。"""
    if site_url:
        return site_url if site_url.endswith("/") else site_url + "/"
    owner, _, name = repo.partition("/")
    return f"https://{owner.lower()}.github.io/{name}/"


def _head_snippet(web_assets: Path | None, rel: str, site_root_url: str) -> str:
    """把主仓 head 片段里的根绝对路径按当前页面深度重写成可用链接。"""
    if not web_assets:
        return ""
    raw = (web_assets / _WEB_SNIPPET).read_text(encoding="utf-8")

    def repl(match: re.Match) -> str:
        attr, value = match.group(1), match.group(2)
        if value == "/og-image.png":  # og:image 必须是绝对 URL，社交平台不解析相对路径
            return f'{attr}="{site_root_url}og-image.png"'
        return f'{attr}="{rel}{value.lstrip("/")}"'

    return re.sub(r'(href|content|src)="(/[^"]*)"', repl, raw).strip()


def _shell(
    *,
    path: str,
    title: str,
    description: str,
    body: str,
    logo: str,
    repo: str,
    web_assets: Path | None,
    site_root_url: str,
    script: str = "",
) -> str:
    rel = _rel_prefix(path)
    snippet = _head_snippet(web_assets, rel, site_root_url)
    nav = f'<nav class="site-nav"><a href="{rel}{_INDEX}">首页</a><a href="{rel}{_LIST}">全部条目</a></nav>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="generator" content="tools/generate_discovery_page.py">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:type" content="website">
{snippet}
<style>{_CSS}</style>
</head>
<body>
<a class="skip" href="#main">跳到正文</a>
<div class="wrap">
<header class="site-head">
<a class="brand" href="{rel}{_INDEX}">{logo}</a>
{nav}
</header>
<main id="main">
{body}
</main>
<footer>
<p class="note">许可：仓库根元数据与目录为 CC0-1.0，<code>tools/</code> 为 MIT，各插件与模板以包内 SPDX 声明为准。</p>
<p class="note">信任模型：创作者签名只证明包来自某把创作者密钥，维护者复签只证明市场审核过这些固定字节——两者都不能证明第三方服务永远安全、合法或可用。</p>
<p class="note">{_repo_link(repo, "README.md", "市场仓库说明")} · {_repo_link(repo, "CATALOG_SCHEMA.md", "目录字段规范")} · {_repo_link(repo, "catalog.json", "catalog.json")} · {_repo_link(repo, _SIG_NAME, _SIG_NAME)}</p>
<p class="note">本页由脚本从已签名的市场目录生成；安装与最终验签在 OmniCrawler 客户端完成。</p>
</footer>
</div>
{script}
</body>
</html>
"""


# ------------------------------------------------------------------------------ 列表卡片

def _card(entry: dict, *, kind: str, official: set[str], order: int) -> str:
    id_ = str(entry.get("id") or "")
    name = str(entry.get("name") or id_)
    version = str(entry.get("version") or "")
    category = str(entry.get("category") or "")
    summary = str(entry.get("summary") or "")
    updated = str(entry.get("updated_at") or "")
    license_ = str(entry.get("license") or "")
    core = str(entry.get("compatible_core") or "")
    tags = [str(tag) for tag in (entry.get("tags") or [])]
    types = [str(item) for item in (entry.get("plugin_types") or [])]
    risk_level, risk_label = _permission_risk(entry)

    meta_bits = [
        f'<span class="k">{_esc(category or "—")}</span>',
        f'<span class="k">核心 {_esc(core or "—")}</span>',
        f'<span class="k">{_esc(license_ or "—")}</span>',
        f'<span class="k">更新 {_esc(updated or "—")}</span>',
    ]
    return (
        f'<article class="card" data-kind="{_esc(kind)}" data-category="{_esc(category)}"'
        f' data-version="{_esc(version)}" data-updated="{_esc(updated)}" data-order="{order}"'
        f' data-search="{_search_blob(id_, name, summary, str(entry.get("publisher") or ""), category, tags, types)}">'
        '<div class="card-head">'
        f'<h3><a href="{_esc(id_)}.html">{_esc(name)}</a></h3>'
        f'<span class="ver" title="版本">v{_esc(version)}</span>'
        "</div>"
        f'<p class="card-id"><code>{_esc(id_)}</code></p>'
        f'<p class="badges">{_badges(entry, official)}'
        f'<span class="b b-risk b-risk-{risk_level}">{_esc(risk_label)}</span></p>'
        f'<p class="summary">{_esc(summary)}</p>'
        f'<p class="tags">{_chips(tags, "tag")} {_chips(types, "chip", "type")}</p>'
        f'<p class="meta">{"".join(meta_bits)}</p>'
        "</article>"
    )


# ------------------------------------------------------------------------------ 三种页面

def _index_page(
    catalog: dict,
    *,
    repo: str,
    official: set[str],
    logo: str,
    web_assets: Path | None,
    site_root_url: str,
    catalog_sha256: str,
    signature_sha256: str,
) -> str:
    plugins = sorted(catalog.get("plugins") or [], key=lambda e: str(e.get("id")))
    templates = sorted(catalog.get("templates") or [], key=lambda e: str(e.get("id")))
    entries = plugins + templates
    reviewed = sum(1 for entry in entries if _reviewed(entry))
    high_risk = sum(1 for entry in entries if _permission_risk(entry)[0] == "high")
    latest = sorted(entries, key=lambda e: str(e.get("updated_at") or ""), reverse=True)[:6]
    certified = sorted(
        [entry for entry in entries if _official(entry, official) and _reviewed(entry)],
        key=lambda e: str(e.get("updated_at") or ""),
        reverse=True,
    )[:6]

    def _category_links(entries_: list[dict], label: str) -> str:
        counts: dict[str, int] = {}
        for entry in entries_:
            category = str(entry.get("category") or "")
            counts[category] = counts.get(category, 0) + 1
        items = "".join(
            f'<li><a href="{_LIST}?cat={_esc(category)}">{_esc(category or "—")}'
            f'<span class="count">{count}</span></a></li>'
            for category, count in sorted(counts.items())
        )
        return f"<h3>{_esc(label)}</h3><ul class=\"cat-list\">{items}</ul>" if items else ""

    def _mini_cards(entries_: list[dict], kind: str) -> str:
        cards = "".join(
            f'<li><a href="{_esc(str(entry.get("id")))}.html">'
            f'<span class="mini-name">{_esc(entry.get("name") or entry.get("id"))}</span>'
            f'<span class="mini-meta">v{_esc(entry.get("version"))} · {_esc(entry.get("updated_at") or "")}</span>'
            f'<span class="mini-badges">{_badges(entry, official)}</span></a></li>'
            for entry in entries_
        )
        return f'<ul class="mini-list" data-kind="{kind}">{cards}</ul>'

    officials = "、".join(str(x) for x in catalog.get("official_publishers") or []) or "—"
    verify_rows = [
        ("catalog.json", f'<code class="hash">{_esc(catalog_sha256)}</code>' if catalog_sha256 else ""),
        (_SIG_NAME, f'<code class="hash">{_esc(signature_sha256)}</code>' if signature_sha256 else ""),
        ("信任根", f'<code>{_esc(catalog.get("trust_public_key_ref"))}</code>'),
        ("目录序列号", f'<code>{_esc(catalog.get("sequence"))}</code>'),
        ("生成时间", f'<code>{_esc(catalog.get("generated_at"))}</code>'),
        ("官方认证作者", _esc(officials)),
    ]

    tombstones = [item for item in (catalog.get("tombstones") or []) if isinstance(item, dict)]
    tomb_html = ""
    if tombstones:
        rows = "".join(
            f'<li><code>{_esc(item.get("id"))}</code><span class="k">{_esc(item.get("removed_at") or "")}</span>'
            f'<span class="why">{_esc(item.get("reason") or "")}</span></li>'
            for item in tombstones
        )
        tomb_html = (
            f'<section class="panel tomb"><h2>已下架（{len(tombstones)}）</h2>'
            f'<ul class="tomb-list">{rows}</ul></section>'
        )

    body = f"""
<section class="hero">
<h1>插件与模板市场</h1>
<p class="lede">本页由市场目录在构建时生成：目录经维护者 Ed25519 签名，<strong>验签先于渲染且 fail-closed</strong>——验签失败则本页永不产出。安装与最终验签在 OmniCrawler 客户端完成，这里只作展示。</p>
<dl class="stats">
<div><dt>插件</dt><dd>{len(plugins)}</dd></div>
<div><dt>模板</dt><dd>{len(templates)}</dd></div>
<div><dt>官方作者条目</dt><dd>{sum(1 for e in entries if _official(e, official))}</dd></div>
<div><dt>维护者已复签</dt><dd>{reviewed}</dd></div>
<div><dt>高权限条目</dt><dd>{high_risk}</dd></div>
<div><dt>目录序列</dt><dd>{_esc(catalog.get("sequence"))}</dd></div>
</dl>
<p class="cta"><a class="btn" href="{_LIST}">浏览全部 {len(entries)} 个条目</a>
<a class="btn btn-ghost" href="{_LIST}?kind=plugin">只看插件</a>
<a class="btn btn-ghost" href="{_LIST}?kind=template">只看模板</a></p>
</section>

<section class="panel">
<h2>本页如何生成</h2>
<p class="note"><code>catalog.json</code> 必须被 <code>{_esc(_SIG_NAME)}</code> 覆盖（算法 ed25519），验签在渲染之前进行且 fail-closed——验签失败则本页不产出。★ 安装与最终验签在 OmniCrawler 客户端完成，本页只作展示，不提供安装动作、也不给出验签结论。</p>
<details><summary>本页渲染所依据的字节（SHA-256）与目录元数据</summary>
{_facts(verify_rows)}
</details>
</section>

<section class="grid-2">
<section class="panel"><h2>分类入口</h2>
{_category_links(plugins, "插件类别")}
{_category_links(templates, "模板类别")}
</section>
<section class="panel"><h2>最近更新</h2>
{_mini_cards(latest, "mixed")}
</section>
</section>

<section class="panel"><h2>官方作者 ∧ 维护者已复签<span class="hint">按更新时间取前 6（判据全部来自已签名目录，不含任何人工排序）</span></h2>
{_mini_cards(certified, "certified")}
</section>
{tomb_html}
"""
    return _shell(
        path=_INDEX,
        title="OmniCrawler 插件与模板市场",
        description="OmniCrawler 插件与模板市场：由已签名的市场目录在构建时生成，验签 fail-closed。",
        body=body,
        logo=logo,
        repo=repo,
        web_assets=web_assets,
        site_root_url=site_root_url,
        script=f"<script>{_JS_LIST}</script>",
    )


def _list_page(
    catalog: dict,
    *,
    repo: str,
    official: set[str],
    logo: str,
    web_assets: Path | None,
    site_root_url: str,
) -> str:
    plugins = sorted(catalog.get("plugins") or [], key=lambda e: str(e.get("id")))
    templates = sorted(catalog.get("templates") or [], key=lambda e: str(e.get("id")))
    total = len(plugins) + len(templates)
    plugin_cards = "".join(_card(entry, kind="plugin", official=official, order=index) for index, entry in enumerate(plugins))
    template_cards = "".join(
        _card(entry, kind="template", official=official, order=len(plugins) + index)
        for index, entry in enumerate(templates)
    )

    def _options(entries: list[dict]) -> str:
        seen = sorted({str(e.get("category") or "") for e in entries if str(e.get("category") or "")})
        return "".join(f'<option value="{_esc(item)}">{_esc(item)}</option>' for item in seen)

    category_groups = ""
    for label, entries in (("插件类别", plugins), ("模板类别", templates)):
        options = _options(entries)
        if options:
            category_groups += f'<optgroup label="{_esc(label)}">{options}</optgroup>'

    body = f"""
<h1 class="page-title">全部条目 <span class="count">{total}</span></h1>
<p class="lede">搜索与筛选只作用于本页展示；点进任意条目查看权限、域名、版本与信任信息。</p>
<form class="toolbar" role="search" onsubmit="return false">
<label class="field"><span class="lbl">搜索</span>
<input id="q" type="search" placeholder="名称 / ID / 简介 / 标签" autocomplete="off"></label>
<label class="field"><span class="lbl">范围</span>
<select id="kind"><option value="all">全部</option><option value="plugin">仅插件</option><option value="template">仅模板</option></select></label>
<label class="field"><span class="lbl">类别</span>
<select id="cat"><option value="all">全部类别</option>{category_groups}</select></label>
<label class="field"><span class="lbl">排序</span>
<select id="sort"><option value="order">目录顺序</option><option value="updated">最近更新</option><option value="version">版本最高</option></select></label>
<p class="live" id="live" role="status" aria-live="polite">共 {total} 个条目</p>
</form>
<section class="group" data-kind="plugin" id="plugins">
<h2>插件 <span class="count">{len(plugins)}</span></h2>
<div class="grid">{plugin_cards}</div>
</section>
<section class="group" data-kind="template" id="templates">
<h2>模板 <span class="count">{len(templates)}</span></h2>
<div class="grid">{template_cards}</div>
</section>
<p class="nomatch" id="nomatch" hidden>没有匹配的条目，试着换个关键词或把「范围」调回「全部」。</p>
"""
    return _shell(
        path=_LIST,
        title="全部条目 — OmniCrawler 插件与模板市场",
        description=f"OmniCrawler 市场全部条目（插件 {len(plugins)} · 模板 {len(templates)}），含信任徽章与权限风险分级。",
        body=body,
        logo=logo,
        repo=repo,
        web_assets=web_assets,
        site_root_url=site_root_url,
        script=f"<script>{_JS_LIST}</script>",
    )


def _detail_page(
    entry: dict,
    *,
    kind: str,
    repo: str,
    official: set[str],
    logo: str,
    web_assets: Path | None,
    site_root_url: str,
    siblings: list[dict],
    listing_markdown: str | None,
) -> str:
    id_ = str(entry.get("id") or "")
    name = str(entry.get("name") or id_)
    version = str(entry.get("version") or "")
    category = str(entry.get("category") or "")
    summary = str(entry.get("summary") or "")
    updated = str(entry.get("updated_at") or "")
    license_ = str(entry.get("license") or "")
    core = str(entry.get("compatible_core") or "")
    publisher = str(entry.get("publisher") or "")
    tags = [str(tag) for tag in (entry.get("tags") or [])]
    types = [str(item) for item in (entry.get("plugin_types") or [])]
    risk_level, risk_label = _permission_risk(entry)
    kind_label = "插件" if kind == "plugin" else "模板"
    rel = _rel_prefix(f"{id_}.html")

    permission_rows: list[tuple[str, str]] = [
        ("权限", _chips([str(p) for p in (entry.get("permissions") or [])], "chip", "perm")),
        ("访问域名", _chips([str(d) for d in (entry.get("domains") or [])], "chip", "domain")),
        ("运行模式", f'<code>{_esc(entry.get("execution_mode"))}</code>' if entry.get("execution_mode") else ""),
        ("需求能力", _chips(_pairs(entry.get("required_capabilities")), "chip", "cap")),
        ("输入文件", _chips([str(f) for f in (entry.get("input_files") or [])], "chip", "file")),
        ("依赖", _chips(_pairs(entry.get("dependencies")), "chip", "dep")),
    ]

    version_rows: list[tuple[str, str]] = []
    versions = entry.get("versions")
    if isinstance(versions, dict) and versions:
        ordered = sorted(versions, key=_version_key, reverse=True)
        version_rows.append((f"已发布版本（{len(ordered)}）", _chips([f"v{v}" for v in ordered], "chip", "ver")))
        for item in ordered:
            payload = versions.get(item)
            digest = str(payload.get("sha256") or "") if isinstance(payload, dict) else ""
            if digest:
                version_rows.append((f"v{_esc(item)} 包 SHA-256", f'<code class="hash">{_esc(digest)}</code>'))
    manifest_sha = str(entry.get("package_manifest_sha256") or "")
    if manifest_sha:
        version_rows.append(("包清单 SHA-256", f'<code class="hash">{_esc(manifest_sha)}</code>'))

    doc_path = str(entry.get("description_file") or "")
    if listing_markdown is None:
        doc_html = '<p class="empty-doc">该条目声明的说明文档缺失，无法展示。请在仓库中核对。</p>'
    elif not listing_markdown.strip():
        doc_html = '<p class="empty-doc">该条目尚未提供说明文档（<code>listing.md</code> 为空）。</p>'
    else:
        doc_html = markdown_to_html(listing_markdown)

    install_hint = (
        "<p>在 OmniCrawler 客户端的「插件市场」面板中按名称或 ID 找到该条目并安装。</p>"
        if kind == "plugin"
        else "<p>在 OmniCrawler 客户端的市场面板中按名称或 ID 找到该条目并安装。</p>"
    )

    sibling_html = ""
    if siblings:
        items = "".join(
            f'<li><a href="{rel}{_esc(str(item.get("id")))}.html">{_esc(item.get("name") or item.get("id"))}'
            f'<span class="count">v{_esc(item.get("version"))}</span></a></li>'
            for item in siblings
        )
        sibling_html = f'<section class="panel"><h2>同类条目</h2><ul class="cat-list">{items}</ul></section>'

    body = f"""
<p class="crumbs"><a href="{rel}{_LIST}">← 全部条目</a> <span>{_esc(kind_label)}</span> <span>{_esc(category or "—")}</span></p>
<header class="detail-head">
<h1>{_esc(name)}</h1>
<p class="card-id"><code id="entry-id">{_esc(id_)}</code>
<button type="button" class="copy" data-copy="{_esc(id_)}">复制 ID</button></p>
<p class="badges">{_badges(entry, official)}<span class="b b-risk b-risk-{risk_level}">{_esc(risk_label)}</span></p>
<p class="summary">{_esc(summary)}</p>
<p class="meta"><span class="k">版本 v{_esc(version)}</span><span class="k">核心 {_esc(core or "—")}</span>
<span class="k">{_esc(license_ or "—")}</span><span class="k">更新 {_esc(updated or "—")}</span>
<span class="k">发布者 {_esc(publisher or "—")}</span></p>
<p class="tags">{_chips(tags, "tag")} {_chips(types, "chip", "type")}</p>
</header>

<section class="panel">
<h2>安装指引</h2>
{install_hint}
<p class="note">安装仅下载并验签；启用这些权限时仍需在项目插件管理中逐项批准（与客户端一致的须知）。本页不代安装，也不给出验签结论；最终验签在客户端完成。</p>
<p class="note">{_repo_link(repo, str(entry.get("plugin_file") or entry.get("template_file") or ""), "该条目的包内文件")}
· {_repo_link(repo, doc_path, "说明文档源文件")}</p>
</section>

<section class="panel">
<h2>权限与域名</h2>
<p class="risk-line"><span class="b b-risk b-risk-{risk_level}">{_esc(risk_label)}</span> <span class="note">{_esc(_risk_reason(entry))}</span></p>
{_facts(permission_rows)}
<p class="note">风险分级判据与客户端同一套（进程内执行，或请求 <code>secrets:read</code> / <code>responses:payload</code> / <code>render:scripted</code> ⇒ 高风险）。</p>
</section>

<section class="panel">
<h2>说明</h2>
<div class="md">{doc_html}</div>
</section>

<section class="panel">
<h2>版本与完整性</h2>
{_facts(version_rows) if version_rows else '<p class="note">该条目未声明版本完整性信息。</p>'}
</section>

<details class="panel">
<summary>信任信息（默认折叠）</summary>
{_facts([
        ("签名算法", f'<code>{_esc(entry.get("signature_algorithm"))}</code>'),
        ("官方认证作者", "是" if _official(entry, official) else "否"),
        ("维护者复签", "有（已审核）" if _reviewed(entry) else "无"),
        ("包清单", _repo_link(repo, str(entry.get("package_manifest_file") or ""), "package.manifest.json")),
        ("创作者包签名", _repo_link(repo, str(entry.get("creator_package_signature_file") or ""), "creator 签名")),
        ("维护者包签名", _repo_link(repo, str(entry.get("maintainer_package_signature_file") or ""), "maintainer 签名")),
        ("条目签名", _repo_link(repo, str(entry.get("signature_file") or ""), "签名文件")),
        ("创作者身份", _repo_link(repo, str(entry.get("creator_identity_file") or ""), "creator.identity")),
        ("兼容核心", f'<code>{_esc(core)}</code>' if core else ""),
        ("状态 schema", f'<code>v{_esc(entry.get("state_schema_version"))}</code>' if entry.get("state_schema_version") is not None else ""),
    ])}
</details>

{sibling_html}
"""
    return _shell(
        path=f"{id_}.html",
        title=f"{name} — OmniCrawler 市场",
        description=f"{name}（{kind_label} v{version}，{publisher or '—'}）：{summary}".strip(),
        body=body,
        logo=logo,
        repo=repo,
        web_assets=web_assets,
        site_root_url=site_root_url,
        script=f"<script>{_JS_DETAIL}</script>",
    )


# ------------------------------------------------------------------------------ 站点装配

def _safe_page_path(entry_id: str) -> str:
    """条目 id → 页面路径。id 约束与 catalog schema 同域；越界即报错（不静默跳过）。"""
    if not _ID_RE.match(entry_id) or ".." in entry_id.split("/"):
        raise ValueError(f"条目 id 不能映射为站点路径（不匹配 {_ID_RE.pattern}）：{entry_id!r}")
    return f"{entry_id}.html"


def build_site(
    catalog: dict,
    *,
    catalog_sha256: str = "",
    signature_sha256: str = "",
    assets_root: Path | None = None,
    repo: str | None = None,
    web_assets: Path | None = None,
    listing_reader=None,
    site_url: str | None = None,
) -> dict[str, str]:
    """渲染整站：`{页面相对路径: HTML}`（index.html / catalog.html / 各条目详情页）。"""
    assets = assets_root or _REGISTRY
    repo_slug = repo or os.environ.get("GITHUB_REPOSITORY") or _FALLBACK_REPO
    site_root_url = _site_root(repo_slug, site_url)
    official = {str(x).strip().casefold() for x in catalog.get("official_publishers") or [] if str(x).strip()}
    logo = _inline_logo(assets)

    plugins = sorted(catalog.get("plugins") or [], key=lambda e: str(e.get("id")))
    templates = sorted(catalog.get("templates") or [], key=lambda e: str(e.get("id")))
    reader = listing_reader or (lambda path: _REGISTRY / path)

    pages: dict[str, str] = {
        _INDEX: _index_page(
            catalog,
            repo=repo_slug,
            official=official,
            logo=logo,
            web_assets=web_assets,
            site_root_url=site_root_url,
            catalog_sha256=catalog_sha256,
            signature_sha256=signature_sha256,
        ),
        _LIST: _list_page(
            catalog,
            repo=repo_slug,
            official=official,
            logo=logo,
            web_assets=web_assets,
            site_root_url=site_root_url,
        ),
    }

    for kind, entries in (("plugin", plugins), ("template", templates)):
        for entry in entries:
            siblings = [
                item
                for item in entries
                if item is not entry and str(item.get("category") or "") == str(entry.get("category") or "")
            ][:6]
            listing: str | None = None
            if entry.get("description_file"):
                source = reader(str(entry["description_file"]))
                if isinstance(source, Path):
                    listing = source.read_text(encoding="utf-8") if source.is_file() else None
                else:
                    listing = source  # 直接喂入文本（测试 / 其他来源）
            pages[_safe_page_path(str(entry.get("id") or ""))] = _detail_page(
                entry,
                kind=kind,
                repo=repo_slug,
                official=official,
                logo=logo,
                web_assets=web_assets,
                site_root_url=site_root_url,
                siblings=siblings,
                listing_markdown=listing,
            )
    return pages


def render(catalog: dict, **kwargs) -> str:
    """仅渲染列表页（便于单测/对照；整站请用 `build_site`）。"""
    return build_site(catalog, **kwargs)[_LIST]


def copy_web_assets(web_assets: Path, out_dir: Path) -> list[str]:
    """把主仓 web 资产复制进产物目录；manifest 内的根绝对路径改为相对（项目页子路径）。"""
    copied: list[str] = []
    for name in _WEB_ASSET_FILES:
        source = web_assets / name
        if not source.is_file():
            raise FileNotFoundError(f"站点资产缺失：{source}")
        if name == "site.webmanifest":
            text = re.sub(r'("src"\s*:\s*")/', r"\1", source.read_text(encoding="utf-8"))
            (out_dir / name).write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(source, out_dir / name)
        copied.append(name)
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fail-closed 生成 Web 发现页")
    parser.add_argument("--output", default="_pages", help="输出目录（Pages artifact）")
    parser.add_argument("--trust", default=None, help="信任根公钥 PEM（默认 keys/plugin_trust.pub.pem）")
    parser.add_argument(
        "--web-assets",
        default=None,
        help=f"主仓站点资产目录（须含 {_WEB_SNIPPET}）；不传则不注入图标/og 资产并打印告警",
    )
    parser.add_argument("--site-url", default=None, help="站点根 URL（默认由 GITHUB_REPOSITORY 推导）")
    args = parser.parse_args(argv)

    try:
        _verify_catalog_signature(_REGISTRY, args.trust)
    except ValueError as exc:
        print(f"[FAIL] catalog 验签失败（fail-closed，拒绝生成）: {exc}")
        return 1
    print("[验签] OK catalog.json 被 catalog.json.sig 覆盖")

    web_assets = Path(args.web_assets).resolve() if args.web_assets else None
    if web_assets is None:
        print("[WARN] 未提供 --web-assets：本次产物不含图标 / og / manifest，仅适用于本地预览")
    elif not (web_assets / _WEB_SNIPPET).is_file():
        print(f"[FAIL] 站点资产不完整（缺 {web_assets / _WEB_SNIPPET}）：拒绝生成半配置站点")
        return 2

    catalog_bytes = (_REGISTRY / "catalog.json").read_bytes()
    sig_path = _REGISTRY / _SIG_NAME
    catalog = json.loads(catalog_bytes.decode("utf-8"))
    pages = build_site(
        catalog,
        catalog_sha256=hashlib.sha256(catalog_bytes).hexdigest(),
        signature_sha256=hashlib.sha256(sig_path.read_bytes()).hexdigest() if sig_path.is_file() else "",
        web_assets=web_assets,
        site_url=args.site_url,
    )

    out_dir = _REGISTRY / args.output
    out_dir.mkdir(parents=True, exist_ok=True)
    for page_path, content in pages.items():
        target = out_dir / page_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    copied = copy_web_assets(web_assets, out_dir) if web_assets else []
    print(f"[OK] 发现页已生成：{out_dir}（{len(pages)} 个页面；站点资产 {len(copied)} 个）")
    return 0


_CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
--bg:#f4f8f6;--panel:#fff;--panel-2:#eef4f0;--text:#11211a;--muted:#5c6f67;
--line:#dce6e0;--accent:#127a58;--accent-soft:#dff7e4;--brand:#0F3D2E;
--official:#186c33;--reviewed:#0b60c4;--high:#b54708;--medium:#8a6d00;--low:#5c6f67;
--toolbar-bg:rgba(244,248,246,.9);
--shadow:0 1px 2px rgba(15,61,46,.06),0 10px 28px rgba(15,61,46,.06);
}
@media (prefers-color-scheme:dark){:root{
--bg:#0b1310;--panel:#131f1a;--panel-2:#182a23;--text:#e6f2eb;--muted:#9cb2a7;
--line:#25362e;--accent:#5DCAA5;--accent-soft:#16342a;--brand:#DFF7E4;
--official:#2ea043;--reviewed:#4493f8;--high:#e3813a;--medium:#d4b03a;--low:#9cb2a7;
--toolbar-bg:rgba(11,19,16,.88);
--shadow:0 1px 2px rgba(0,0,0,.4),0 10px 28px rgba(0,0,0,.35);
}}
html{-webkit-text-size-adjust:100%}
body{margin:0;color:var(--text);background:radial-gradient(1100px 420px at 8% -12%,var(--accent-soft),transparent 68%),var(--bg);
font:16px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;font-size:.86em}
.wrap{max-width:1140px;margin:0 auto;padding:1.4rem 1.15rem 3.2rem}
.skip{position:absolute;left:-9999px}
.skip:focus{left:1rem;top:1rem;background:var(--panel);color:var(--text);padding:.55rem .9rem;border-radius:10px;z-index:9}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
.site-head{display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;padding:.4rem 0 1rem}
.logo svg{display:block;width:min(240px,52vw);height:auto}
.logo .wm-dark{display:none}
@media (prefers-color-scheme:dark){.logo .wm-light{display:none}.logo .wm-dark{display:block}}
.site-nav{display:flex;gap:1rem;font-size:.94rem}
h1{margin:.1rem 0 .55rem;font-size:clamp(1.55rem,2.6vw,2.15rem);letter-spacing:-.015em}
h2{margin:0 0 .9rem;font-size:1.02rem;display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}
.page-title{margin-top:.2rem}
.lede{margin:0;max-width:74ch;color:var(--muted)}
.lede strong{color:var(--text)}
.hero{padding:.4rem 0 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.6rem;margin:1.5rem 0 0;padding:0}
.stats>div{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:.6rem .85rem;box-shadow:var(--shadow)}
.stats dt{color:var(--muted);font-size:.76rem;letter-spacing:.04em}
.stats dd{margin:.2rem 0 0;font-weight:600;font-size:1.02rem;word-break:break-all}
.cta{display:flex;flex-wrap:wrap;gap:.5rem;margin:1.2rem 0 0}
.btn{display:inline-block;background:var(--brand);color:#fff;border:1px solid var(--brand);border-radius:10px;padding:.45rem .9rem;font-size:.92rem}
@media (prefers-color-scheme:dark){.btn{background:var(--accent-soft);color:var(--text);border-color:var(--line)}}
.btn-ghost{background:var(--panel);color:var(--text);border-color:var(--line)}
.btn:hover{text-decoration:none;filter:brightness(1.06)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:1rem 1.15rem;margin:1.2rem 0;box-shadow:var(--shadow)}
.grid-2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1.2rem}
.note{color:var(--muted);font-size:.9rem;margin:.5rem 0}
.hint{color:var(--muted);font-size:.8rem;font-weight:400}
details{margin:.15rem 0}
details>summary{cursor:pointer;color:var(--accent);font-size:.92rem;width:fit-content}
details.panel>summary{color:var(--text);font-weight:600;font-size:1rem}
details>summary::marker{color:var(--muted)}
.toolbar{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:.8rem 1rem;align-items:flex-end;
background:var(--toolbar-bg);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);
padding:.9rem 0 .85rem;margin:1.2rem 0 1.4rem}
.field{display:flex;flex-direction:column;gap:.3rem}
.lbl{font-size:.76rem;letter-spacing:.03em;color:var(--muted)}
input,select{font:inherit;font-size:.92rem;color:var(--text);background:var(--panel);border:1px solid var(--line);
border-radius:10px;padding:.45rem .6rem;min-width:12rem;max-width:100%}
input[type=search]{min-width:16rem}
.live{margin:0 0 .35rem auto;color:var(--muted);font-size:.86rem;font-variant-numeric:tabular-nums}
.group{margin:0 0 2rem}
.count{background:var(--panel-2);color:var(--muted);border-radius:999px;padding:.06rem .55rem;font-size:.8rem;font-weight:500}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:.9rem}
.card{display:flex;flex-direction:column;gap:.5rem;background:var(--panel);border:1px solid var(--line);
border-radius:14px;padding:.95rem 1rem 1rem;box-shadow:var(--shadow);break-inside:avoid}
.card-head{display:flex;align-items:baseline;gap:.55rem;justify-content:space-between}
.card h3{margin:0;font-size:1.02rem;line-height:1.35;word-break:break-word}
.ver{flex:none;font-size:.78rem;color:var(--brand);background:var(--accent-soft);border:1px solid var(--line);
border-radius:999px;padding:.08rem .5rem;font-variant-numeric:tabular-nums}
@media (prefers-color-scheme:dark){.ver{color:var(--text)}}
.card-id{margin:0;color:var(--muted);font-size:.82rem;word-break:break-all;display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}
.badges{margin:0;display:flex;flex-wrap:wrap;gap:.35rem;align-items:center}
.b{display:inline-block;padding:.1rem .5rem;border-radius:999px;font-size:.76rem;line-height:1.5;white-space:nowrap}
.b-official{background:var(--official);color:#fff}
.b-reviewed{background:var(--reviewed);color:#fff}
.b-high{background:var(--high);color:#fff}
.b-pub{background:var(--panel-2);color:var(--muted);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.b-risk{background:var(--panel-2);border:1px solid var(--line)}
.b-risk-high{color:var(--high);border-color:var(--high)}
.b-risk-medium{color:var(--medium);border-color:var(--medium)}
.b-risk-low{color:var(--muted)}
.summary{margin:0;font-size:.92rem}
.tags{margin:0;display:flex;flex-wrap:wrap;gap:.3rem}
.tag,.chip{display:inline-block;font-size:.74rem;padding:.08rem .45rem;border-radius:7px;background:var(--panel-2);color:var(--muted)}
.chip{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.72rem}
.meta{margin:0;display:flex;flex-wrap:wrap;gap:.35rem .2rem;color:var(--muted);font-size:.78rem}
.k{color:var(--muted)}
.meta .k+.k::before{content:"·";margin:0 .38rem;color:var(--line)}
.facts{margin:.2rem 0 .3rem;display:grid;grid-template-columns:auto 1fr;gap:.35rem .8rem;font-size:.84rem}
.facts dt{color:var(--muted);white-space:nowrap}
.facts dd{margin:0;display:flex;flex-wrap:wrap;gap:.3rem;align-items:baseline;word-break:break-word}
.hash{word-break:break-all;font-size:.76rem;color:var(--muted)}
.crumbs{margin:.2rem 0 1rem;color:var(--muted);font-size:.88rem;display:flex;gap:.6rem;flex-wrap:wrap}
.crumbs span::before{content:"/";margin-right:.6rem;color:var(--line)}
.detail-head{margin:0 0 1.2rem}
.copy{font:inherit;font-size:.78rem;color:var(--text);background:var(--panel);border:1px solid var(--line);
border-radius:8px;padding:.15rem .55rem;cursor:pointer}
.copy:hover{border-color:var(--accent)}
.risk-line{display:flex;align-items:center;gap:.5rem;margin:.2rem 0 .6rem;flex-wrap:wrap}
.empty-doc{margin:0;color:var(--muted);background:var(--panel-2);border:1px dashed var(--line);border-radius:12px;padding:.8rem 1rem}
.cat-list{list-style:none;margin:0;padding:0;display:grid;gap:.45rem}
.cat-list a{display:flex;justify-content:space-between;gap:.6rem;align-items:center;background:var(--panel-2);
border:1px solid var(--line);border-radius:10px;padding:.45rem .7rem;font-size:.9rem;color:var(--text)}
.cat-list a:hover{border-color:var(--accent);text-decoration:none}
.cat-list h3{margin:.8rem 0 .4rem;font-size:.9rem;color:var(--muted)}
.mini-list{list-style:none;margin:0;padding:0;display:grid;gap:.45rem}
.mini-list a{display:grid;grid-template-columns:1fr auto;gap:.3rem .6rem;align-items:center;background:var(--panel-2);
border:1px solid var(--line);border-radius:10px;padding:.5rem .7rem;color:var(--text)}
.mini-list a:hover{border-color:var(--accent);text-decoration:none}
.mini-name{font-size:.92rem}
.mini-meta{color:var(--muted);font-size:.78rem;font-variant-numeric:tabular-nums}
.mini-badges{grid-column:1/-1;display:flex;gap:.3rem;flex-wrap:wrap}
.tomb-list{list-style:none;margin:0;padding:0;display:grid;gap:.5rem}
.tomb-list li{background:var(--panel-2);border:1px solid var(--line);border-radius:12px;padding:.6rem .8rem;display:flex;flex-wrap:wrap;gap:.6rem}
.tomb-list .why{color:var(--muted);font-size:.9rem}
.nomatch{background:var(--panel);border:1px dashed var(--line);border-radius:14px;padding:1.4rem;text-align:center;color:var(--muted)}
.md{margin:.2rem 0 0;font-size:.95rem}
.md h2,.md h3,.md h4{margin:1.3rem 0 .5rem;font-size:1rem}
.md h2:first-child,.md h3:first-child{margin-top:.2rem}
.md p{margin:.55rem 0}
.md ul,.md ol{margin:.5rem 0;padding-left:1.3rem}
.md li{margin:.2rem 0}
.md blockquote{margin:.7rem 0;padding:.4rem .9rem;border-left:3px solid var(--line);color:var(--muted)}
.md hr{border:0;border-top:1px solid var(--line);margin:1.1rem 0}
.md pre.code{background:var(--panel-2);border:1px solid var(--line);border-radius:10px;padding:.7rem .9rem;overflow-x:auto;line-height:1.5}
.md pre.code code{font-size:.82rem;background:none;padding:0}
.md code{background:var(--panel-2);border-radius:5px;padding:.05rem .3rem}
.table-wrap{overflow-x:auto;margin:.7rem 0}
.md table{border-collapse:collapse;width:100%;font-size:.86rem}
.md th,.md td{border:1px solid var(--line);padding:.4rem .55rem;text-align:left;vertical-align:top}
.md th{background:var(--panel-2);white-space:nowrap}
footer{border-top:1px solid var(--line);margin-top:1.6rem;padding-top:1rem}
[hidden]{display:none!important}
@media print{.toolbar,.copy,.site-nav{display:none}.card{box-shadow:none}}
"""

_JS_LIST = """
(function(){
  var q=document.getElementById('q'),kind=document.getElementById('kind'),
      cat=document.getElementById('cat'),sort=document.getElementById('sort'),
      live=document.getElementById('live'),nomatch=document.getElementById('nomatch');
  if(!q||!live){return;}
  var cards=[].slice.call(document.querySelectorAll('article.card'));
  var groups=[].slice.call(document.querySelectorAll('section.group[data-kind]'));
  var total=cards.length;
  function nums(v){var m=String(v||'').match(/\\d+/g)||[];return m.map(Number);}
  function cmpVersion(a,b){
    var A=nums(a.dataset.version),B=nums(b.dataset.version),i;
    for(i=0;i<Math.max(A.length,B.length);i++){var x=A[i]||0,y=B[i]||0;if(x!==y){return y-x;}}
    return 0;
  }
  function order(list,mode){
    var items=[].slice.call(list.children);
    if(mode==='updated'){
      items.sort(function(a,b){return String(b.dataset.updated||'').localeCompare(String(a.dataset.updated||''));});
    }else if(mode==='version'){
      items.sort(cmpVersion);
    }else{
      items.sort(function(a,b){return Number(a.dataset.order)-Number(b.dataset.order);});
    }
    items.forEach(function(el){list.appendChild(el);});
    return items;
  }
  function apply(){
    var needle=q.value.trim().toLowerCase(),k=kind.value,c=cat.value,s=sort.value,shown=0;
    groups.forEach(function(g){
      var list=g.querySelector('.grid');
      if(!list){return;}
      var items=order(list,s),n=0;
      items.forEach(function(el){
        var ok=true;
        if(needle&&String(el.dataset.search||'').indexOf(needle)<0){ok=false;}
        if(ok&&c!=='all'&&el.dataset.category!==c){ok=false;}
        if(ok&&k!=='all'&&el.dataset.kind!==k){ok=false;}
        el.hidden=!ok;
        if(ok){n++;}
      });
      g.hidden=(n===0);
      var badge=g.querySelector('.count');
      if(badge){badge.textContent=String(n);}
      shown+=n;
    });
    live.textContent='显示 '+shown+' / '+total;
    nomatch.hidden=(shown!==0);
  }
  [q,kind,cat,sort].forEach(function(el){
    el.addEventListener('input',apply);
    el.addEventListener('change',apply);
  });
  var params=new URLSearchParams(location.search);
  ['q','kind','cat','sort'].forEach(function(key){
    var value=params.get(key);
    if(value){document.getElementById(key).value=value;}
  });
  apply();
})();
"""

_JS_DETAIL = """
(function(){
  document.querySelectorAll('[data-copy]').forEach(function(btn){
    btn.addEventListener('click',function(){
      var value=btn.getAttribute('data-copy')||'',label=btn.textContent;
      function done(ok){
        btn.textContent=ok?'已复制':'已选中，请按 Ctrl/Cmd+C';
        setTimeout(function(){btn.textContent=label;},1600);
      }
      if(navigator.clipboard&&navigator.clipboard.writeText){
        navigator.clipboard.writeText(value).then(function(){done(true);},function(){done(false);});
      }else{
        done(false);
      }
    });
  });
})();
"""


if __name__ == "__main__":
    raise SystemExit(main())
