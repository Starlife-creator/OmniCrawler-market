# SPDX-License-Identifier: MIT
"""发现页 HTML 渲染与受限 Markdown / M5 徽章语义辅助模块。"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from pathlib import Path

from ._css import _CSS
from ._js import _JS_DETAIL, _JS_LIST, _JS_THEME

# 站内到仓库文件的链接、站点地址回落值（CI 里由 GITHUB_REPOSITORY 覆盖）
_FALLBACK_REPO = "Starlife-creator/OmniCrawler-market"
_SIG_NAME = "catalog.json.sig"
_INDEX = "index.html"
_LIST = "catalog.html"
_LOGO_DIR = Path("assets") / "branding" / "lockup"
_FACTS_LIMIT = 12
_TAG_CHIP_LIMIT = 20
_HOME_TAG_LIMIT = 12

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
_COMPONENT_BADGE_TEXT = "只托管配方声明 · 字节从上游拉取"
_KIND_LABELS = {"plugin": "插件", "template": "模板", "component": "组件"}


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
    """渲染一组静态 chip；超量时折叠计数，避免长列表撑爆卡片。"""
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


def _tag_buttons(items: list[object]) -> str:
    """渲染卡片内可点击筛选的标签胶囊（全部经 HTML 实体转义）。"""
    values = [_text(item).strip() for item in items]
    values = [v for v in values if v]
    if not values:
        return ""
    head, rest = values[:_FACTS_LIMIT], values[_FACTS_LIMIT:]
    out = "".join(
        f'<button type="button" class="tag tag-btn" data-card-tag="{_esc(v.casefold())}"'
        f' title="按标签「{_esc(v)}」筛选">{_esc(v)}</button>'
        for v in head
    )
    if rest:
        out += f'<span class="tag" title="{_esc("、".join(rest))}">…等 {len(values)} 项</span>'
    return out


def _facts(rows: list[tuple[str, str]]) -> str:
    """渲染 <dt>/<dd> 事实表；值为空的行自动跳过。"""
    body = "".join(f"<dt>{_esc(label)}</dt><dd>{value}</dd>" for label, value in rows if value)
    return f'<dl class="facts">{body}</dl>' if body else ""


def _version_key(version: object) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(version)))


def _format_bytes(raw: object) -> str:
    """将字节计数格式化为可读大小（保留精确字节数便于核对）。"""
    if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
        return ""
    if raw >= 1024 * 1024:
        return f"{raw / (1024 * 1024):.2f} MB（{raw:,} 字节）"
    if raw >= 1024:
        return f"{raw / 1024:.1f} KB（{raw:,} 字节）"
    return f"{raw:,} 字节"


def _component_category(entry: dict) -> str:
    """提取组件分类（优先显式 category，否则取 entry.engine 或回落 component）。"""
    explicit = str(entry.get("category") or "").strip()
    if explicit:
        return explicit
    entry_spec = entry.get("entry")
    if isinstance(entry_spec, dict):
        engine = str(entry_spec.get("engine") or "").strip()
        if engine:
            return f"component/{engine}"
    return "component"


def _entry_category(entry: dict, kind: str) -> str:
    if kind == "component":
        return _component_category(entry)
    return str(entry.get("category") or "")


def _entry_tags(entry: dict, kind: str) -> list[str]:
    """提取单条目的可筛选标签列表（按条目内大小写折叠去重，保留首次展示名）。"""
    candidates: list[str] = [str(tag).strip() for tag in (entry.get("tags") or []) if str(tag).strip()]
    if kind == "component":
        candidates.extend(str(p).strip() for p in (entry.get("platforms") or []) if str(p).strip())
        entry_spec = entry.get("entry")
        if isinstance(entry_spec, dict):
            engine = str(entry_spec.get("engine") or "").strip()
            if engine:
                candidates.append(engine)
    seen: set[str] = set()
    unique: list[str] = []
    for item in candidates:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _collect_catalog_tags(
    tagged_entries: list[tuple[str, dict]],
    *,
    limit: int = _TAG_CHIP_LIMIT,
) -> list[tuple[str, str, int]]:
    """聚合全目录标签并返回确定性排序的 `[(key_casefold, display_label, count), ...]`。

    若目录中所有条目均未声明标签/平台（如极简测试样例），则回退使用条目类别派生胶囊。
    """
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for kind, entry in tagged_entries:
        for label in _entry_tags(entry, kind):
            key = label.casefold()
            counts[key] = counts.get(key, 0) + 1
            labels.setdefault(key, label)
    if not counts:
        for kind, entry in tagged_entries:
            cat = _entry_category(entry, kind).strip()
            if cat:
                key = cat.casefold()
                counts[key] = counts.get(key, 0) + 1
                labels.setdefault(key, cat)
    ordered_keys = sorted(counts, key=lambda k: (-counts[k], k, labels[k]))
    return [(key, labels[key], counts[key]) for key in ordered_keys[:limit]]


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


def _badges(entry: dict, official: set[str], *, kind: str = "") -> str:
    """徽章（M5：官方＝作者身份、已审核＝流程状态、高权限＝权限风险，组件额外标注只托管配方声明）。"""
    badges = []
    if kind == "component":
        badges.append(f'<span class="b b-recipe">{_esc(_COMPONENT_BADGE_TEXT)}</span>')
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
    """内联品牌字标（浅/深两版，随 prefers-color-scheme 或 data-theme 切换），保持零外部请求。"""
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
    page_js: str = "",
) -> str:
    rel = _rel_prefix(path)
    snippet = _head_snippet(web_assets, rel, site_root_url)
    idx_cur = ' aria-current="page"' if path == _INDEX else ""
    list_cur = ' aria-current="page"' if path == _LIST else ""
    nav = (
        f'<nav class="site-nav"><a class="nav-link" href="{rel}{_INDEX}"{idx_cur}>首页</a>'
        f'<a class="nav-link" href="{rel}{_LIST}"{list_cur}>全部条目</a>'
        '<button type="button" class="theme-btn" id="theme-toggle"'
        ' aria-label="切换配色主题（跟随系统、浅色或深色）">主题：跟随系统</button></nav>'
    )
    combined_js = (_JS_THEME.strip() + "\n" + page_js.strip()).strip()
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
<header class="site-head">
<div class="head-inner">
<a class="brand" href="{rel}{_INDEX}">{logo}</a>
{nav}
</div>
</header>
<div class="wrap">
<main id="main">
{body}
</main>
<footer>
<p class="note">许可：仓库根元数据与目录为 CC0-1.0，<code>tools/</code> 为 MIT，各插件、模板与组件配方以条目或上游 SPDX 声明为准。</p>
<p class="note">信任模型：创作者签名只证明包来自某把创作者密钥，维护者复签只证明市场审核过这些固定字节；组件分支只托管配方声明、字节从上游拉取并校验哈希——均不能证明第三方服务永远安全、合法或可用。</p>
<p class="note">{_repo_link(repo, "README.md", "市场仓库说明")} · {_repo_link(repo, "CATALOG_SCHEMA.md", "目录字段规范")} · {_repo_link(repo, "catalog.json", "catalog.json")} · {_repo_link(repo, _SIG_NAME, _SIG_NAME)}</p>
<p class="note">本页由脚本从已签名的市场目录生成；安装与最终验签在 OmniCrawler 客户端完成。</p>
</footer>
</div>
<script>{combined_js}</script>
</body>
</html>
"""


# ------------------------------------------------------------------------------ 列表卡片与胶囊栏

def _tag_filter_bar(tag_stats: list[tuple[str, str, int]]) -> str:
    """渲染列表页可点击标签胶囊筛选栏（含「全部标签」重置胶囊与卡片外标签兜底位）。"""
    chips = [
        '<button type="button" class="tag-chip is-active" data-tag-chip=""'
        ' data-tag-label="全部标签" aria-pressed="true">全部标签</button>'
    ]
    for key, label, count in tag_stats:
        chips.append(
            f'<button type="button" class="tag-chip" data-tag-chip="{_esc(key)}"'
            f' data-tag-label="{_esc(label)}" aria-pressed="false">'
            f'{_esc(label)}<span class="tag-chip-num">{count}</span></button>'
        )
    chips.append(
        '<button type="button" class="tag-chip" id="active-custom-tag"'
        ' data-tag-chip="" aria-pressed="false" hidden></button>'
    )
    return (
        '<div class="tag-bar" id="tag-filters" role="group" aria-label="按标签胶囊筛选">'
        '<span class="tag-bar-label">标签筛选</span>'
        + "".join(chips)
        + "</div>"
    )


def _card(entry: dict, *, kind: str, official: set[str], order: int) -> str:
    id_ = str(entry.get("id") or "")
    name = str(entry.get("name") or id_)
    version = str(entry.get("version") or "")
    category = _entry_category(entry, kind)
    summary = str(entry.get("summary") or "")
    updated = str(entry.get("updated_at") or "")
    license_ = str(entry.get("license") or "")
    core = str(entry.get("compatible_core") or "")
    tags = [str(tag) for tag in (entry.get("tags") or [])]
    types = [str(item) for item in (entry.get("plugin_types") or [])]
    kind_label = _KIND_LABELS.get(kind, "条目")
    tag_keys = [item.casefold() for item in _entry_tags(entry, kind)]
    tags_attr = _esc(json.dumps(tag_keys, ensure_ascii=False))

    if kind == "component":
        platforms = [str(p) for p in (entry.get("platforms") or [])]
        architectures = [str(a) for a in (entry.get("architectures") or [])]
        entry_spec = entry.get("entry") if isinstance(entry.get("entry"), dict) else {}
        engine = str(entry_spec.get("engine") or "")
        protocol = str(entry_spec.get("protocol") or "")
        size_text = _format_bytes(entry.get("declared_total_bytes"))
        if not summary:
            summary = f"组件配方声明（引擎 {engine or '—'} · 协议 {protocol or '—'}），构件字节由客户端按 SHA-256 从上游拉取。"
        meta_bits = [
            f'<span class="k">{_esc(category or "—")}</span>',
            f'<span class="k">下载量 {_esc(size_text or "—")}</span>',
            f'<span class="k">{_esc(license_ or "上游许可")}</span>',
        ]
        if updated:
            meta_bits.append(f'<span class="k">更新 {_esc(updated)}</span>')
        chip_html = " ".join(
            part
            for part in (
                _tag_buttons(platforms),
                _chips(architectures, "chip", "arch"),
                _chips([x for x in (engine, protocol) if x], "chip", "type"),
                _tag_buttons(tags),
            )
            if part
        )
        risk_badge = '<span class="b b-risk b-risk-low">纯数据配方</span>'
        search_attr = _search_blob(
            id_, name, summary, str(entry.get("publisher") or ""),
            category, tags, platforms, architectures, engine, protocol, "component", "组件", "recipe",
        )
    else:
        risk_level, risk_label = _permission_risk(entry)
        risk_badge = f'<span class="b b-risk b-risk-{risk_level}">{_esc(risk_label)}</span>'
        perms = [str(p).strip() for p in (entry.get("permissions") or []) if str(p).strip()]
        meta_bits = [
            f'<span class="k">{_esc(category or "—")}</span>',
            f'<span class="k">核心 {_esc(core or "—")}</span>',
            f'<span class="k">{_esc(license_ or "—")}</span>',
        ]
        if kind == "plugin" and perms:
            meta_bits.append(f'<span class="k">权限 {len(perms)} 项</span>')
        meta_bits.append(f'<span class="k">更新 {_esc(updated or "—")}</span>')
        chip_html = " ".join(
            part
            for part in (_tag_buttons(tags), _chips(types, "chip", "type"))
            if part
        )
        search_attr = _search_blob(id_, name, summary, str(entry.get("publisher") or ""), category, tags, types)

    tags_block = f'<p class="tags">{chip_html}</p>' if chip_html.strip() else ""
    return (
        f'<article class="card" data-kind="{_esc(kind)}" data-name="{_esc(name)}"'
        f' data-category="{_esc(category)}" data-tags="{tags_attr}"'
        f' data-version="{_esc(version)}" data-updated="{_esc(updated)}" data-order="{order}"'
        f' data-search="{search_attr}">'
        '<div class="card-head">'
        f'<h3><a href="{_esc(id_)}.html">{_esc(name)}</a></h3>'
        f'<span class="ver" title="版本">v{_esc(version)}</span>'
        "</div>"
        f'<p class="card-id"><span class="kind-pill kind-{_esc(kind)}">{_esc(kind_label)}</span>'
        f"<code>{_esc(id_)}</code></p>"
        f'<p class="badges">{_badges(entry, official, kind=kind)} {risk_badge}</p>'
        f'<p class="summary">{_esc(summary)}</p>'
        f"{tags_block}"
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
    components = sorted(catalog.get("components") or [], key=lambda e: str(e.get("id")))
    tagged_entries: list[tuple[str, dict]] = (
        [("plugin", e) for e in plugins]
        + [("template", e) for e in templates]
        + [("component", e) for e in components]
    )
    entries = [e for _k, e in tagged_entries]
    reviewed = sum(1 for entry in entries if _reviewed(entry))
    high_risk = sum(1 for _k, entry in tagged_entries if _k != "component" and _permission_risk(entry)[0] == "high")
    latest = sorted(tagged_entries, key=lambda pair: str(pair[1].get("updated_at") or ""), reverse=True)[:6]
    certified = sorted(
        [(k, entry) for k, entry in tagged_entries if _official(entry, official) and _reviewed(entry)],
        key=lambda pair: str(pair[1].get("updated_at") or ""),
        reverse=True,
    )[:6]
    home_tags = _collect_catalog_tags(tagged_entries, limit=_HOME_TAG_LIMIT)

    def _category_links(entries_: list[dict], kind_key: str, label: str) -> str:
        counts: dict[str, int] = {}
        for entry in entries_:
            category = _entry_category(entry, kind_key)
            counts[category] = counts.get(category, 0) + 1
        items = "".join(
            (
                f'<li><a href="{_LIST}?kind={_esc(kind_key)}'
                f'{"&amp;cat=" + _esc(urllib.parse.quote(category, safe="")) if category else ""}">'
                f'{_esc(category or "—")}'
                f'<span class="count">{count}</span></a></li>'
            )
            for category, count in sorted(counts.items())
        )
        return f'<h3>{_esc(label)}</h3><ul class="cat-list">{items}</ul>' if items else ""

    def _home_tag_links(stats: list[tuple[str, str, int]]) -> str:
        if not stats:
            return ""
        links = "".join(
            f'<a class="home-tag-link" href="{_LIST}?tag={_esc(urllib.parse.quote(key, safe=""))}">'
            f'{_esc(label)}<span class="tag-chip-num">{count}</span></a>'
            for key, label, count in stats
        )
        return f'<h3>热门标签</h3><div class="home-tags">{links}</div>'

    def _mini_cards(pairs: list[tuple[str, dict]], list_kind: str) -> str:
        items_html: list[str] = []
        for entry_kind, entry in pairs:
            summary_text = str(entry.get("summary") or "").strip()
            summary_html = f'<span class="mini-summary">{_esc(summary_text)}</span>' if summary_text else ""
            items_html.append(
                f'<li><a href="{_esc(str(entry.get("id")))}.html">'
                f'<span class="mini-name">{_esc(entry.get("name") or entry.get("id"))}</span>'
                f'<span class="mini-meta">v{_esc(entry.get("version"))}'
                f'{" · " + _esc(entry.get("updated_at")) if entry.get("updated_at") else ""}</span>'
                f"{summary_html}"
                f'<span class="mini-badges">{_badges(entry, official, kind=entry_kind)}</span></a></li>'
            )
        return f'<ul class="mini-list" data-kind="{list_kind}">{"".join(items_html)}</ul>'

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

    comp_home_html = ""
    if components:
        comp_home_html = (
            '<section class="panel"><h2>组件配方声明'
            f'<span class="hint">{_esc(_COMPONENT_BADGE_TEXT)}</span></h2>'
            f'{_mini_cards([("component", c) for c in components[:6]], "component")}'
            "</section>"
        )

    body = f"""
<section class="hero">
<p class="eyebrow">ED25519 FAIL-CLOSED REGISTRY · ZERO EXTERNAL SUBRESOURCES</p>
<h1>OmniCrawler 市场</h1>
<p class="lede">本页由市场目录在构建时生成：目录经维护者 Ed25519 签名，<strong>验签先于渲染且 fail-closed</strong>——验签失败则本页永不产出。涵盖插件、模板与组件配方声明；安装与最终验签在 OmniCrawler 客户端完成，这里只作展示。</p>
<dl class="stats">
<div><dt>插件</dt><dd>{len(plugins)}</dd></div>
<div><dt>模板</dt><dd>{len(templates)}</dd></div>
<div><dt>组件</dt><dd>{len(components)}</dd></div>
<div><dt>官方作者条目</dt><dd>{sum(1 for e in entries if _official(e, official))}</dd></div>
<div><dt>维护者已复签</dt><dd>{reviewed}</dd></div>
<div><dt>高权限条目</dt><dd>{high_risk}</dd></div>
<div><dt>目录序列</dt><dd>{_esc(catalog.get("sequence"))}</dd></div>
</dl>
<p class="cta"><a class="btn" href="{_LIST}">浏览全部 {len(entries)} 个条目</a>
<a class="btn btn-ghost" href="{_LIST}?kind=plugin">只看插件</a>
<a class="btn btn-ghost" href="{_LIST}?kind=template">只看模板</a>
<a class="btn btn-ghost" href="{_LIST}?kind=component">只看组件</a></p>
</section>

<section class="panel">
<h2>本页如何生成</h2>
<p class="note"><code>catalog.json</code> 必须被 <code>{_esc(_SIG_NAME)}</code> 覆盖（算法 ed25519），验签在渲染之前进行且 fail-closed——验签失败则本页不产出。组件分支只托管配方声明（<code>recipe.json</code>），构件字节由客户端从上游拉取并逐项核对 SHA-256。★ 安装与最终验签在 OmniCrawler 客户端完成，本页只作展示，不提供安装动作、也不给出验签结论。</p>
<details><summary>本页渲染所依据的字节（SHA-256）与目录元数据</summary>
{_facts(verify_rows)}
</details>
</section>

<section class="grid-2">
<section class="panel"><h2>分类入口</h2>
{_category_links(plugins, "plugin", "插件类别")}
{_category_links(templates, "template", "模板类别")}
{_category_links(components, "component", "组件类别")}
{_home_tag_links(home_tags)}
</section>
<section class="panel"><h2>最近更新</h2>
{_mini_cards(latest, "mixed")}
</section>
</section>

<section class="panel"><h2>官方作者 ∧ 维护者已复签<span class="hint">按更新时间取前 6（判据全部来自已签名目录，不含任何人工排序）</span></h2>
{_mini_cards(certified, "certified")}
</section>
{comp_home_html}
{tomb_html}
"""
    return _shell(
        path=_INDEX,
        title="OmniCrawler 插件、模板与组件市场",
        description="OmniCrawler 插件、模板与组件市场：由已签名的市场目录在构建时生成，验签 fail-closed。",
        body=body,
        logo=logo,
        repo=repo,
        web_assets=web_assets,
        site_root_url=site_root_url,
        page_js=_JS_LIST,
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
    components = sorted(catalog.get("components") or [], key=lambda e: str(e.get("id")))
    total = len(plugins) + len(templates) + len(components)
    tagged_entries: list[tuple[str, dict]] = (
        [("plugin", e) for e in plugins]
        + [("template", e) for e in templates]
        + [("component", e) for e in components]
    )
    tag_stats = _collect_catalog_tags(tagged_entries, limit=_TAG_CHIP_LIMIT)
    tag_bar_html = _tag_filter_bar(tag_stats)

    plugin_cards = "".join(
        _card(entry, kind="plugin", official=official, order=index)
        for index, entry in enumerate(plugins)
    )
    template_cards = "".join(
        _card(entry, kind="template", official=official, order=len(plugins) + index)
        for index, entry in enumerate(templates)
    )
    component_cards = "".join(
        _card(entry, kind="component", official=official, order=len(plugins) + len(templates) + index)
        for index, entry in enumerate(components)
    )

    def _options(entries: list[dict], kind_key: str) -> str:
        seen = sorted({_entry_category(e, kind_key) for e in entries if _entry_category(e, kind_key)})
        return "".join(f'<option value="{_esc(item)}">{_esc(item)}</option>' for item in seen)

    category_groups = ""
    for label, kind_key, entries in (
        ("插件类别", "plugin", plugins),
        ("模板类别", "template", templates),
        ("组件类别", "component", components),
    ):
        options = _options(entries, kind_key)
        if options:
            category_groups += f'<optgroup label="{_esc(label)}">{options}</optgroup>'

    body = f"""
<header class="list-hero">
<div>
<p class="eyebrow">CATALOG EXPLORER · PLUGINS · TEMPLATES · RECIPES</p>
<h1 class="page-title">全部条目 <span class="count">{total}</span></h1>
<p class="lede">搜索与筛选只作用于本页展示；按 <kbd>/</kbd> 可快速聚焦搜索框，点击下方标签胶囊或卡片标签可组合筛选，点进任意条目查看权限、配方声明、版本与信任信息。</p>
</div>
<div class="seg-tabs" role="tablist" aria-label="按市场分支快速切换">
<button type="button" class="seg-tab is-active" role="tab" aria-selected="true" data-kind-tab="all">全部 <span class="seg-num">{total}</span></button>
<button type="button" class="seg-tab" role="tab" aria-selected="false" data-kind-tab="plugin">插件 <span class="seg-num">{len(plugins)}</span></button>
<button type="button" class="seg-tab" role="tab" aria-selected="false" data-kind-tab="template">模板 <span class="seg-num">{len(templates)}</span></button>
<button type="button" class="seg-tab" role="tab" aria-selected="false" data-kind-tab="component">组件 <span class="seg-num">{len(components)}</span></button>
</div>
</header>
<form class="toolbar" role="search" onsubmit="return false">
<label class="field field-search"><span class="lbl">搜索</span>
<span class="search-wrap"><input id="q" type="search" aria-label="搜索市场条目" placeholder="按 / 搜索名称、标签、ID…" autocomplete="off"><kbd class="search-kbd" aria-hidden="true">/</kbd></span></label>
<label class="field"><span class="lbl">范围</span>
<select id="kind" aria-label="按市场分支筛选"><option value="all">全部</option><option value="plugin">仅插件</option><option value="template">仅模板</option><option value="component">仅组件</option></select></label>
<label class="field"><span class="lbl">类别</span>
<select id="cat" aria-label="按条目类别筛选"><option value="all">全部类别</option>{category_groups}</select></label>
<label class="field"><span class="lbl">排序</span>
<select id="sort" aria-label="排序方式"><option value="order">默认排序</option><option value="name">名称 A→Z</option><option value="category">类别排序</option><option value="updated">最近更新</option><option value="version">版本最高</option></select></label>
<button type="button" class="btn-reset" id="reset-filters" hidden>重置筛选</button>
<p class="live" id="live" role="status" aria-live="polite">共 {total} 个条目</p>
</form>
{tag_bar_html}
<section class="group" data-kind="plugin" id="plugins">
<h2>插件 <span class="count">{len(plugins)}</span></h2>
<div class="grid">{plugin_cards}</div>
</section>
<section class="group" data-kind="template" id="templates">
<h2>模板 <span class="count">{len(templates)}</span></h2>
<div class="grid">{template_cards}</div>
</section>
<section class="group" data-kind="component" id="components">
<h2>组件 <span class="count">{len(components)}</span></h2>
<div class="grid">{component_cards}</div>
</section>
<p class="nomatch" id="nomatch" hidden>没有匹配的条目，试着换个关键词、切换标签或点击「重置筛选」。</p>
"""
    return _shell(
        path=_LIST,
        title="全部条目 — OmniCrawler 插件、模板与组件市场",
        description=(
            f"OmniCrawler 市场全部条目（插件 {len(plugins)} · 模板 {len(templates)} · 组件 {len(components)}），"
            "含信任徽章、配方声明与权限风险分级。"
        ),
        body=body,
        logo=logo,
        repo=repo,
        web_assets=web_assets,
        site_root_url=site_root_url,
        page_js=_JS_LIST,
    )


def _component_sections(entry: dict, *, repo: str, doc_path: str) -> tuple[str, str, list[tuple[str, str]]]:
    """渲染组件专属的（安装指引面板、配方与上游构件面板、信任事实行）。"""
    recipe_file = str(entry.get("recipe_file") or "")
    recipe_digest = str(entry.get("recipe_digest") or "")
    platforms = [str(p) for p in (entry.get("platforms") or [])]
    architectures = [str(a) for a in (entry.get("architectures") or [])]
    entry_spec = entry.get("entry") if isinstance(entry.get("entry"), dict) else {}
    entry_engine = str(entry_spec.get("engine") or "")
    entry_protocol = str(entry_spec.get("protocol") or "")
    entry_path = str(entry_spec.get("path") or "")
    size_text = _format_bytes(entry.get("declared_total_bytes"))
    license_ = str(entry.get("license") or "")

    links = " · ".join(
        link
        for link in (
            _repo_link(repo, recipe_file, "该组件的配方文件 (recipe.json)"),
            _repo_link(repo, doc_path, "说明文档源文件"),
        )
        if link
    )
    install_panel = f"""<section class="panel">
<h2>安装指引（配方拉取）</h2>
<p>在 OmniCrawler 客户端或 CLI 中按组件 ID 预览并拉取：<code>omnicrawler components inspect-recipe</code>（仅预览声明，零下载）或显式带 <code>--download</code> 执行拉取与本地 SHA-256 核验。</p>
<p class="note"><strong>{_esc(_COMPONENT_BADGE_TEXT)}</strong>：市场仓库不托管大型二进制或模型字节；下载经客户端受控出站完成，任一构件 SHA-256 不匹配即拒绝装配。</p>
<p class="note">{links}</p>
</section>"""

    artifact_items: list[str] = []
    for idx, artifact in enumerate(entry.get("artifacts") or [], 1):
        if not isinstance(artifact, dict):
            continue
        art_url = str(artifact.get("url") or "")
        art_sha = str(artifact.get("sha256") or "")
        art_size = _format_bytes(artifact.get("size"))
        size_part = f' <span class="k">（{_esc(art_size)}）</span>' if art_size else ""
        artifact_items.append(
            f"<li><strong>构件 #{idx}</strong>{size_part}<br>"
            f"上游地址：<code>{_esc(art_url or '—')}</code><br>"
            f'SHA-256：<code class="hash">{_esc(art_sha or "—")}</code></li>'
        )
    artifacts_html = (
        f'<ul class="artifact-list">{"".join(artifact_items)}</ul>'
        if artifact_items
        else '<p class="note">未声明上游构件。</p>'
    )

    recipe_rows: list[tuple[str, str]] = [
        ("托管边界", f'<span class="b b-recipe">{_esc(_COMPONENT_BADGE_TEXT)}</span>'),
        ("支持平台", _chips(platforms, "chip", "plat")),
        ("支持架构", _chips(architectures, "chip", "arch")),
        ("目标引擎", f"<code>{_esc(entry_engine)}</code>" if entry_engine else ""),
        ("入口协议", f"<code>{_esc(entry_protocol)}</code>" if entry_protocol else ""),
        ("装配路径", f"<code>{_esc(entry_path)}</code>" if entry_path else ""),
        ("声明总大小", _esc(size_text)),
        ("许可声明", _esc(license_ or "以上游构件各自的许可证为准")),
        ("配方 SHA-256", f'<code class="hash">{_esc(recipe_digest)}</code>' if recipe_digest else ""),
    ]

    recipe_panel = f"""<section class="panel">
<h2>配方声明与上游构件</h2>
{_facts(recipe_rows)}
<h3>上游构件清单</h3>
{artifacts_html}
<p class="note">配方是纯数据声明而非可执行脚本（禁止安装钩子与路径穿越）；本页只展示上游声明地址，不发起任何外部请求。</p>
</section>"""

    trust_rows: list[tuple[str, str]] = [
        ("条目类型", "组件配方（<code>components</code>）"),
        ("配方文件", _repo_link(repo, recipe_file, "recipe.json")),
        ("配方摘要", f'<code class="hash">{_esc(recipe_digest)}</code>' if recipe_digest else ""),
        ("配方签名", _repo_link(repo, str(entry.get("recipe_signature_file") or ""), "recipe.json.sig")),
        ("创作者身份", _repo_link(repo, str(entry.get("creator_identity_file") or ""), "creator.identity")),
    ]
    return install_panel, recipe_panel, trust_rows


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
    category = _entry_category(entry, kind)
    summary = str(entry.get("summary") or "")
    updated = str(entry.get("updated_at") or "")
    license_ = str(entry.get("license") or "")
    core = str(entry.get("compatible_core") or "")
    publisher = str(entry.get("publisher") or "")
    tags = [str(tag) for tag in (entry.get("tags") or [])]
    types = [str(item) for item in (entry.get("plugin_types") or [])]
    kind_label = _KIND_LABELS.get(kind, "条目")
    rel = _rel_prefix(f"{id_}.html")

    doc_path = str(entry.get("description_file") or "")
    if listing_markdown is None:
        doc_html = '<p class="empty-doc">该条目声明的说明文档缺失，无法展示。请在仓库中核对。</p>'
    elif not listing_markdown.strip():
        doc_html = '<p class="empty-doc">该条目尚未提供说明文档（<code>listing.md</code> 为空）。</p>'
    else:
        doc_html = markdown_to_html(listing_markdown)

    sibling_html = ""
    if siblings:
        items = "".join(
            f'<li><a href="{rel}{_esc(str(item.get("id")))}.html">{_esc(item.get("name") or item.get("id"))}'
            f'<span class="count">v{_esc(item.get("version"))}</span></a></li>'
            for item in siblings
        )
        sibling_html = f'<section class="panel"><h2>同类条目</h2><ul class="cat-list">{items}</ul></section>'

    if kind == "component":
        platforms = [str(p) for p in (entry.get("platforms") or [])]
        architectures = [str(a) for a in (entry.get("architectures") or [])]
        size_text = _format_bytes(entry.get("declared_total_bytes"))
        if not summary:
            summary = f"{name}（{_COMPONENT_BADGE_TEXT}）"
        install_panel, middle_panel, comp_trust_rows = _component_sections(
            entry, repo=repo, doc_path=doc_path
        )
        comp_trust_rows.insert(1, ("官方认证作者", "是" if _official(entry, official) else "否"))
        comp_trust_rows.insert(2, ("维护者复签", "有（已审核）" if _reviewed(entry) else "无"))
        version_rows: list[tuple[str, str]] = [
            ("当前配方版本", f"<code>v{_esc(version)}</code>" if version else ""),
            ("配方 SHA-256", f'<code class="hash">{_esc(entry.get("recipe_digest"))}</code>' if entry.get("recipe_digest") else ""),
            ("声明总字节数", _esc(size_text)),
        ]
        risk_badge = '<span class="b b-risk b-risk-low">纯数据配方</span>'
        head_tags = " ".join(
            part
            for part in (_chips(platforms, "tag"), _chips(architectures, "chip", "arch"), _chips(tags, "tag"))
            if part
        )
        meta_line = (
            f'<span class="k">版本 v{_esc(version)}</span>'
            f'<span class="k">下载量 {_esc(size_text or "—")}</span>'
            f'<span class="k">{_esc(license_ or "上游许可")}</span>'
            f'<span class="k">发布者 {_esc(publisher or "—")}</span>'
        )
        trust_facts_html = _facts(comp_trust_rows)
    else:
        risk_level, risk_label = _permission_risk(entry)
        risk_badge = f'<span class="b b-risk b-risk-{risk_level}">{_esc(risk_label)}</span>'
        head_tags = " ".join(
            part for part in (_chips(tags, "tag"), _chips(types, "chip", "type")) if part
        )
        meta_line = (
            f'<span class="k">版本 v{_esc(version)}</span><span class="k">核心 {_esc(core or "—")}</span>'
            f'<span class="k">{_esc(license_ or "—")}</span><span class="k">更新 {_esc(updated or "—")}</span>'
            f'<span class="k">发布者 {_esc(publisher or "—")}</span>'
        )
        permission_rows: list[tuple[str, str]] = [
            ("权限", _chips([str(p) for p in (entry.get("permissions") or [])], "chip", "perm")),
            ("访问域名", _chips([str(d) for d in (entry.get("domains") or [])], "chip", "domain")),
            ("运行模式", f'<code>{_esc(entry.get("execution_mode"))}</code>' if entry.get("execution_mode") else ""),
            ("需求能力", _chips(_pairs(entry.get("required_capabilities")), "chip", "cap")),
            ("输入文件", _chips([str(f) for f in (entry.get("input_files") or [])], "chip", "file")),
            ("依赖", _chips(_pairs(entry.get("dependencies")), "chip", "dep")),
        ]
        version_rows = []
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

        install_hint = (
            "<p>在 OmniCrawler 客户端的「OmniCrawler 市场」面板中按名称或 ID 找到该条目并安装。</p>"
            if kind == "plugin"
            else "<p>在 OmniCrawler 客户端的市场面板中按名称或 ID 找到该条目并安装。</p>"
        )
        install_panel = f"""<section class="panel">
<h2>安装指引</h2>
{install_hint}
<p class="note">安装仅下载并验签；启用这些权限时仍需在项目插件管理中逐项批准（与客户端一致的须知）。本页不代安装，也不给出验签结论；最终验签在客户端完成。</p>
<p class="note">{_repo_link(repo, str(entry.get("plugin_file") or entry.get("template_file") or ""), "该条目的包内文件")}
· {_repo_link(repo, doc_path, "说明文档源文件")}</p>
</section>"""
        middle_panel = f"""<section class="panel">
<h2>权限与域名</h2>
<p class="risk-line"><span class="b b-risk b-risk-{risk_level}">{_esc(risk_label)}</span> <span class="note">{_esc(_risk_reason(entry))}</span></p>
{_facts(permission_rows)}
<p class="note">风险分级判据与客户端同一套（进程内执行，或请求 <code>secrets:read</code> / <code>responses:payload</code> / <code>render:scripted</code> ⇒ 高风险）。</p>
</section>"""
        trust_facts_html = _facts([
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
        ])

    head_tags_block = f'<p class="tags">{head_tags}</p>' if head_tags.strip() else ""
    body = f"""
<p class="crumbs"><a href="{rel}{_LIST}">← 全部条目</a> <span>{_esc(kind_label)}</span> <span>{_esc(category or "—")}</span></p>
<header class="detail-head">
<h1>{_esc(name)}</h1>
<p class="card-id"><code id="entry-id">{_esc(id_)}</code>
<button type="button" class="copy" data-copy="{_esc(id_)}">复制 ID</button></p>
<p class="badges">{_badges(entry, official, kind=kind)} {risk_badge}</p>
<p class="summary">{_esc(summary)}</p>
<p class="meta">{meta_line}</p>
{head_tags_block}
</header>

{install_panel}

{middle_panel}

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
{trust_facts_html}
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
        page_js=_JS_DETAIL,
    )
