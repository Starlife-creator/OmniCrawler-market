#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Web 发现页生成器（§10.12）：fail-closed 验签 catalog ⇒ 渲染静态发现页。

★ 安全语义（§10.12 硬性要求）：
- **先验签后渲染**：catalog.json 必须被 catalog.json.sig 覆盖（信任根公钥校验），
  验签失败 ⇒ 拒绝生成（退出码 1）——被篡改的目录永远上不了 Pages。
- 渲染语义与客户端一致（M5）：官方＝publisher 命中 official_publishers；
  已审核＝维护者复签文件存在；已下架条目单列（不得静默消失）。

用法：python tools/generate_discovery_page.py [--output _pages]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REGISTRY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REGISTRY / "tools"))

from catalog_lib.signing import _verify_catalog_signature  # noqa: E402


def _badge(publisher: str, official: set[str], reviewed: bool) -> str:
    badges = []
    if publisher and publisher.strip().casefold() in official:
        badges.append('<span class="b b-official">官方</span>')
    if reviewed:
        badges.append('<span class="b b-reviewed">已审核</span>')
    return " ".join(badges)


def render(catalog: dict) -> str:
    official = {str(x).strip().casefold() for x in catalog.get("official_publishers") or [] if str(x).strip()}
    rows = []
    for entry in sorted(catalog.get("plugins") or [], key=lambda e: str(e.get("id"))):
        publisher = str(entry.get("publisher") or "")
        reviewed = bool(str(entry.get("maintainer_package_signature_file") or "").strip())
        summary = str(entry.get("summary") or "")
        name = str(entry.get("name") or entry.get("id") or "")
        rows.append(
            "<tr>"
            f"<td>{name}</td>"
            f"<td>v{entry.get('version', '')}</td>"
            f"<td>{_badge(publisher, official, reviewed)}</td>"
            f"<td>{publisher}</td>"
            f"<td>{summary}</td>"
            "</tr>"
        )
    tombstones = catalog.get("tombstones") or []
    tomb_html = ""
    if tombstones:
        items = "".join(
            f"<li><code>{item.get('id', '')}</code>（{item.get('removed_at', '')}）：{item.get('reason', '')}</li>"
            for item in tombstones
            if isinstance(item, dict)
        )
        tomb_html = f"<h2>已下架</h2><ul>{items}</ul>"
    officials = "、".join(catalog.get("official_publishers") or []) or "—"
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>OmniCrawler 插件市场</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:.5rem;text-align:left}}
.b{{display:inline-block;padding:.1rem .5rem;border-radius:.7rem;font-size:.85rem}}
.b-official{{background:#1a7f37;color:#fff}}.b-reviewed{{background:#0969da;color:#fff}}
.note{{color:#555;font-size:.9rem}}
</style></head><body>
<h1>OmniCrawler 插件市场</h1>
<p class="note">本页由市场目录自动生成：目录经维护者签名（ed25519），构建时验签 fail-closed——
验签失败则本页拒绝生成。官方认证作者：{officials}</p>
<h2>插件（{len(rows)}）</h2>
<table><tr><th>名称</th><th>版本</th><th>信任徽章</th><th>发布者</th><th>简介</th></tr>
{''.join(rows)}</table>
{tomb_html}
</body></html>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fail-closed 生成 Web 发现页")
    parser.add_argument("--output", default="_pages", help="输出目录（Pages artifact）")
    parser.add_argument("--trust", default=None, help="信任根公钥 PEM（默认 keys/plugin_trust.pub.pem）")
    args = parser.parse_args(argv)

    try:
        _verify_catalog_signature(_REGISTRY, args.trust)
    except ValueError as exc:
        print(f"[FAIL] catalog 验签失败（fail-closed，拒绝生成）: {exc}")
        return 1
    print("[验签] OK catalog.json 被 catalog.json.sig 覆盖")

    catalog = json.loads((_REGISTRY / "catalog.json").read_text(encoding="utf-8"))
    out_dir = _REGISTRY / args.output
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render(catalog), encoding="utf-8")
    print(f"[OK] 发现页已生成：{out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
