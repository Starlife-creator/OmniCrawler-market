#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""发现页渲染回归检查（validate.yml 调用）。

守住的语义，每条都带**反向断言**（构造会失败的输入，确认它真会失败）：

1. **转义**：目录字段与 `listing.md` 一旦不转义，页面结构就能被投稿内容改写。
   用「敌意目录 + 敌意说明文档」渲染，断言危险片段**未原样出现**、且**转义形式确实出现**
   （只断言「没出现」不够——渲染器整段丢弃该字段也会通过）。同时断言
   `[x](javascript:...)` 构造不出可点击链接、图片语法不产出 `<img>`。
2. **结构完整**：必须产出 `index.html` + `catalog.html` + **每个条目一页**；
   列表页卡片数与目录条目数一致（分组容器的同名属性不得混进来）。
3. **链接完整**：每页的相对链接都必须能解析到产物内真实存在的文件
   （详情页落在子目录，前缀写错就会当场红）；站外链接只允许指向市场仓库/站点自身。
4. **零外部子资源**：任何页面都不得引站外脚本/样式/字体/图片。
5. **站点资产**：head 片段按页面深度重写、manifest 去掉根绝对路径、片段本身不落站点根；
   资产目录不完整 ⇒ 拒绝生成（不为半配置站点出页）。
6. **确定性**：同目录两次渲染逐字节相同。
7. **fail-closed**：信任根换成非信任根公钥 ⇒ 退出码 1 且不产出文件。
8. **M5 语义一致**：徽章与权限风险分级必须与客户端同一判据。
9. **id → 路径**：不安全的 id 必须报错，而不是静默生成可穿越的路径。

用法：python tools/check_discovery_page.py
"""

from __future__ import annotations

import json
import posixpath
import re
import shutil
import sys
import tempfile
from pathlib import Path

_REGISTRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REGISTRY / "tools"))

import generate_discovery_page as page  # noqa: E402
from generate_discovery_page import build_site, main as generate_main, markdown_to_html  # noqa: E402

_TRUST_ROOT = _REGISTRY / "keys" / "plugin_trust.pub.pem"

_RAW_DANGER = ("<script>alert(", "<img src=x onerror=", "<svg/onload=", 'onmouseover="alert(')
_ESCAPED_MARK = "&lt;script&gt;alert("

_EXTERNAL_SUBRESOURCE = re.compile(
    r"<(?:script|img|link|iframe|source|video|audio|embed|object|track)\b[^>]*\b(?:src|href|data)\s*=\s*[\"']?(?:https?:)?//",
    re.IGNORECASE,
)
_ATTR_RE = re.compile(r'(?:href|src)="([^"]*)"')

_HOSTILE_LISTING = """# 标题 <script>alert('listing')</script>

正文里有 <img src=x onerror=alert(1)> 与 [危险链接](javascript:alert(2)) 和 [正常链接](https://example.com/x)。

![图片](https://evil.example/pic.png)

| 列 <script>alert('table')</script> | 值 |
|---|---|
| `code` | **粗** |

```
<script>alert('fence')</script>
```

- 项 <svg/onload=alert(3)>
"""

_HOSTILE = {
    "schema_version": 1,
    "generated_at": "2026-01-01T00:00:00+00:00",
    "sequence": 1,
    "publisher": "starlife",
    "trust_model": 'dual-rail-ed25519"><script>alert(0)</script>',
    "official_publishers": ['starlife"><script>alert(1)</script>'],
    "trust_public_key_ref": "keys/plugin_trust.pub.pem",
    "plugins": [
        {
            "id": "evil-entry",
            "name": "<img src=x onerror=alert(1)>",
            "version": "1.0.0",
            "publisher": "</p><script>alert(2)</script>",
            "category": "source",
            "plugin_types": ["source"],
            "summary": "<script>alert(3)</script> & <b>bold</b>",
            "tags": ["<svg/onload=alert(4)>"],
            "permissions": ["network:scoped", "<script>alert(5)</script>"],
            "compatible_core": ">=0.1",
            "license": "MIT",
            "updated_at": "2026-01-01",
            "execution_mode": "subprocess",
            "state_schema_version": 1,
            "domains": ["example.com"],
            "input_files": ["*.csv"],
            "required_capabilities": {"view.richtext": ">=1"},
            "dependencies": [{"name": "<script>alert(6)</script>", "version": ">=1"}],
            "versions": {"1.0.0": {"sha256": "0" * 64}},
            "package_manifest_sha256": "0" * 64,
            "maintainer_package_signature_file": "x.sig",
            "description_file": "plugins/evil/listing.md",
        }
    ],
    "templates": [
        {
            "id": "cms/market/evil-template",
            "name": "模板 <script>alert(7)</script>",
            "version": "1.0.0",
            "publisher": "starlife",
            "category": "cms/evil",
            "summary": "<script>alert(8)</script>",
            "tags": [],
            "license": "MIT",
            "updated_at": "2026-01-01",
            "template_file": "templates/evil/template.yaml",
            "maintainer_package_signature_file": "x.sig",
            "description_file": "templates/evil/listing.md",
        }
    ],
    "tombstones": [
        {"id": "<script>alert(9)</script>", "removed_at": "2026-01-01", "reason": "<img src=x onerror=alert(10)>"}
    ],
}


def _load_catalog() -> dict:
    return json.loads((_REGISTRY / "catalog.json").read_text(encoding="utf-8"))


def _fake_web_assets(root: Path) -> Path:
    """造一份与主仓同构的站点资产目录（含 head 片段与根绝对路径）。"""
    root.mkdir(parents=True, exist_ok=True)
    snippet = (
        "<!-- 片段 -->\n"
        '<link rel="icon" href="/favicon.ico" sizes="any">\n'
        '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">\n'
        '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">\n'
        '<link rel="manifest" href="/site.webmanifest">\n'
        '<meta name="theme-color" content="#0F3D2E">\n'
        '<meta property="og:image" content="/og-image.png">\n'
    )
    (root / "html-head-snippet.html").write_text(snippet, encoding="utf-8")
    for name in page._WEB_ASSET_FILES:
        target = root / name
        if name == "site.webmanifest":
            target.write_text(
                json.dumps(
                    {"name": "OmniCrawler", "icons": [{"src": "/android-chrome-192x192.png", "sizes": "192x192"}]},
                    indent=2,
                ),
                encoding="utf-8",
            )
        else:
            target.write_bytes(b"\x89PNG\r\n\x1a\n")
    return root


# --------------------------------------------------------------------------- 各组断言

def check_escaping() -> list[str]:
    pages = build_site(_HOSTILE, assets_root=_REGISTRY, listing_reader=lambda _path: _HOSTILE_LISTING)
    joined = "\n".join(pages.values())
    problems = []
    for marker in _RAW_DANGER:
        if marker in joined:
            problems.append(f"未转义的危险片段原样出现在产物中：{marker}")
    if _ESCAPED_MARK not in joined:
        problems.append("未观察到转义后的片段：渲染器可能丢弃了该字段而不是转义它")
    if "&lt;script&gt;alert(&#x27;listing&#x27;)" not in joined:
        problems.append("listing.md 的内容未被转义地渲染（期望引号也随实体转义）")
    if 'href="javascript:' in joined:
        problems.append("listing.md 里的 javascript: 链接被渲染成可点击链接")
    if "<img" in joined:
        problems.append("产物中出现了 <img>（图片语法不得渲染，页面须零外部请求）")
    if joined.count("<script") != len(pages):
        problems.append(f"每页应恰好 1 个内联脚本，实际共 {joined.count('<script')} / {len(pages)} 页")
    return problems


def check_markdown() -> list[str]:
    rendered = markdown_to_html(_HOSTILE_LISTING)
    problems = []
    for fragment in ("<h2>", "<table>", "<ul>", '<pre class="code">', "<code>code</code>", "<strong>粗</strong>"):
        if fragment not in rendered:
            problems.append(f"Markdown 渲染缺少预期构造：{fragment}")
    if "<img" in rendered:
        problems.append("Markdown 渲染产出了 <img>（图片语法不得渲染，页面须零外部请求）")
    if 'href="javascript:' in rendered:
        problems.append("Markdown 渲染把 javascript: 变成了可点击链接")
    if "javascript:alert(2)" not in rendered:
        problems.append("非 http(s) 链接应以纯文本保留（既不可点击、也不得丢失信息）")
    if markdown_to_html("").strip():
        problems.append("空说明文档应渲染为空内容（由调用方给出「未提供说明文档」提示）")
    return problems


def check_structure(catalog: dict, pages: dict[str, str]) -> list[str]:
    problems = []
    plugins = catalog.get("plugins") or []
    templates = catalog.get("templates") or []
    expected = {"index.html", "catalog.html"} | {f"{entry['id']}.html" for entry in plugins + templates}
    missing = sorted(expected - set(pages))
    unexpected = sorted(set(pages) - expected)
    if missing:
        problems.append(f"缺少页面：{missing}")
    if unexpected:
        problems.append(f"多出预期外的页面：{unexpected}")
    list_page = pages.get("catalog.html", "")
    for kind, entries in (("plugin", plugins), ("template", templates)):
        actual = list_page.count(f'<article class="card" data-kind="{kind}"')
        if actual != len(entries):
            problems.append(f"列表页 {kind} 卡片数 {actual} != 目录条目数 {len(entries)}")
    for path, content in pages.items():
        if content.count("<details") != content.count("</details>"):
            problems.append(f"{path}: <details> 与 </details> 不配对")
        if content.count("<article") != content.count("</article>"):
            problems.append(f"{path}: <article> 与 </article> 不配对")
        ids = re.findall(r'\sid="([^"]+)"', content)
        duplicated = sorted({item for item in ids if ids.count(item) > 1})
        if duplicated:
            problems.append(f"{path}: 重复 id {duplicated}")
    return problems


def check_links(pages: dict[str, str], repo: str) -> list[str]:
    problems = []
    for path, content in pages.items():
        base = posixpath.dirname(path)  # 产物路径一律 POSIX 风格，避免 Windows 上被转成反斜杠
        for target in sorted(set(_ATTR_RE.findall(content))):
            if not target or target.startswith("#") or target.startswith("data:"):
                continue
            if target.startswith(("http://", "https://")):
                if target.startswith("http://"):
                    problems.append(f"{path}: 明文 http 链接 {target}")
                elif not (target.startswith(f"https://github.com/{repo}") or "github.io/" in target):
                    problems.append(f"{path}: 指向仓库之外的站外链接 {target}")
                continue
            resolved = posixpath.normpath(posixpath.join(base, target.split("#")[0].split("?")[0]))
            if resolved not in pages:
                problems.append(f"{path}: 相对链接解析不到产物文件 -> {target}（解析为 {resolved}）")
    return problems


def check_self_contained(pages: dict[str, str]) -> list[str]:
    problems = []
    for path, content in pages.items():
        match = _EXTERNAL_SUBRESOURCE.search(content)
        if match:
            problems.append(f"{path}: 引用了站外子资源 {match.group(0)[:60]}")
        if "@import" in content or "url(http" in content:
            problems.append(f"{path}: 存在 @import / url(http...) 站外引用")
        if '<link rel="stylesheet"' in content:
            problems.append(f"{path}: 引用了外部样式表（必须内联）")
    return problems


def check_web_assets() -> list[str]:
    problems = []
    workdir = Path(tempfile.mkdtemp(prefix="_pages-selftest-", dir=_REGISTRY))
    try:
        assets = _fake_web_assets(workdir / "web")
        catalog = _load_catalog()
        pages = build_site(catalog, assets_root=_REGISTRY, web_assets=assets)
        root_head = pages.get("index.html", "")
        nested_head = pages.get("cms/market/discourse-topics.html", "")
        if 'href="favicon.ico"' not in root_head:
            problems.append("根页 head 未把 /favicon.ico 重写为相对路径")
        if 'href="../../favicon.ico"' not in nested_head:
            problems.append("子目录详情页 head 未按深度重写图标路径")
        if 'content="https://starlife-creator.github.io/OmniCrawler-market/og-image.png"' not in root_head:
            problems.append("og:image 未写成绝对 URL（社交平台不解析相对路径）")

        out = workdir / "out"
        out.mkdir()
        copied = page.copy_web_assets(assets, out)
        if sorted(copied) != sorted(page._WEB_ASSET_FILES):
            problems.append("复制清单与 _WEB_ASSET_FILES 不一致")
        if page._WEB_SNIPPET in copied:
            problems.append("head 片段不应被复制进站点根（它已被消费进各页 head）")
        manifest_path = out / "site.webmanifest"
        if not manifest_path.is_file():
            problems.append("site.webmanifest 未被复制进产物（清单被削减时会走到这里，不能崩）")
        else:
            manifest = manifest_path.read_text(encoding="utf-8")
            if re.search(r'"src"\s*:\s*"/', manifest):
                problems.append("site.webmanifest 内的图标仍是根绝对路径（项目页子路径下会 404）")

        incomplete = workdir / "web-incomplete"
        incomplete.mkdir()
        rc = generate_main(["--web-assets", str(incomplete), "--output", str(workdir / "out2")])
        if rc != 2:
            problems.append(f"站点资产不完整时退出码应为 2，实际 {rc}")
        if (workdir / "out2" / "index.html").exists():
            problems.append("站点资产不完整时仍产出了页面")
        return problems
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def check_determinism(catalog: dict) -> list[str]:
    if build_site(catalog, assets_root=_REGISTRY) != build_site(catalog, assets_root=_REGISTRY):
        return ["同一目录两次渲染结果不一致（产物混入了时间戳或随机量）"]
    return []


def check_m5_semantics() -> list[str]:
    """徽章与风险分级必须与客户端同一判据（镜像被改动时这条要能抓住）。"""
    problems = []

    def risk(entry: dict) -> str:
        return page._permission_risk(entry)[0]

    for case in (
        ({"permissions": ["secrets:read"]}, "high"),
        ({"permissions": ["responses:payload"]}, "high"),
        ({"permissions": ["render:scripted"]}, "high"),
        ({"execution_mode": "in_process", "permissions": []}, "high"),
        ({"permissions": ["network:scoped"]}, "medium"),
        ({"permissions": ["records:read"]}, "low"),
    ):
        if risk(case[0]) != case[1]:
            problems.append(f"风险分级不符：{case[0]} 应判 {case[1]}，实际 {risk(case[0])}")

    official = {"starlife"}
    badges = page._badges(
        {"publisher": "starlife", "maintainer_package_signature_file": "x", "permissions": ["secrets:read"]}, official
    )
    for label in ("官方", "已审核", "高权限"):
        if label not in badges:
            problems.append(f"徽章缺少「{label}」")
    if "已审核" in page._badges({"publisher": "starlife", "permissions": []}, official):
        problems.append("无维护者复签时不应出现「已审核」")
    return problems


def check_id_paths() -> list[str]:
    problems = []
    for hostile in ("../../etc/passwd", "UPPER/case", "evil entry", "../x"):
        try:
            page._safe_page_path(hostile)
        except ValueError:
            continue
        problems.append(f"不安全 id 未被拒绝：{hostile!r}")
    if page._safe_page_path("cms/market/ok-id") != "cms/market/ok-id.html":
        problems.append("正常的层级 id 未能映射为页面路径")
    return problems


def check_fail_closed() -> list[str]:
    others = sorted(p for p in (_REGISTRY / "keys").glob("*.pub.pem") if p.name != _TRUST_ROOT.name)
    if not others:
        return ["keys/ 下缺少非信任根公钥，无法做 fail-closed 反向断言"]
    workdir = Path(tempfile.mkdtemp(prefix="_pages-selftest-", dir=_REGISTRY))
    try:
        out = workdir / "out"
        print("（下面这条 [FAIL] 是预期的反向断言输出：换了信任根，生成器必须拒绝）")
        rc = generate_main(["--trust", str(others[0]), "--output", str(out)])
        problems = []
        if rc != 1:
            problems.append(f"信任根不匹配时退出码应为 1，实际 {rc}")
        if (out / "index.html").exists():
            problems.append("信任根不匹配时仍然写入了 index.html（不是 fail-closed）")
        return problems
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main() -> int:
    catalog = _load_catalog()
    pages = build_site(catalog, catalog_sha256="a" * 64, signature_sha256="b" * 64, assets_root=_REGISTRY)
    problems: list[str] = []
    problems += check_escaping()
    problems += check_markdown()
    problems += check_structure(catalog, pages)
    problems += check_links(pages, page._FALLBACK_REPO)
    problems += check_self_contained(pages)
    problems += check_web_assets()
    problems += check_determinism(catalog)
    problems += check_m5_semantics()
    problems += check_id_paths()
    problems += check_fail_closed()
    if problems:
        for item in problems:
            print(f"  - {item}")
        print(f"FAIL discovery page: {len(problems)} 项断言未通过")
        return 1
    print(
        "OK discovery page: 转义/结构/链接/零外部子资源/站点资产/确定性/M5 语义/id 路径/fail-closed 全部通过"
        f"（{len(pages)} 页；插件 {len(catalog.get('plugins') or [])}，模板 {len(catalog.get('templates') or [])}）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
