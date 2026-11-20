# SPDX-License-Identifier: MIT
"""发现页整站装配、fail-closed 验签门禁与站点资产复制。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parents[1]
_REGISTRY = _TOOLS_DIR.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from catalog_lib.signing import _verify_catalog_signature

from ._pages import (
    _FALLBACK_REPO,
    _ID_RE,
    _INDEX,
    _LIST,
    _SIG_NAME,
    _WEB_ASSET_FILES,
    _WEB_SNIPPET,
    _detail_page,
    _entry_category,
    _index_page,
    _inline_logo,
    _list_page,
    _site_root,
)


def _safe_page_path(entry_id: str) -> str:
    """条目 id → 页面路径。id 约束与 catalog schema 同域；越界即报错（不静默跳过）。"""
    if not _ID_RE.match(entry_id) or ".." in entry_id.split("/"):
        raise ValueError(f"条目 id 不能映射为站点路径（不匹配 {_ID_RE.pattern}）：{entry_id!r}")
    return f"{entry_id}.html"


def verify_registry_catalog(registry: Path = _REGISTRY, trust: str | None = None) -> None:
    """先验签后渲染：校验 catalog.json 被 catalog.json.sig 覆盖，失败抛 ValueError。"""
    _verify_catalog_signature(registry, trust)


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
    components = sorted(catalog.get("components") or [], key=lambda e: str(e.get("id")))
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

    for kind, entries in (("plugin", plugins), ("template", templates), ("component", components)):
        for entry in entries:
            siblings = [
                item
                for item in entries
                if item is not entry and _entry_category(item, kind) == _entry_category(entry, kind)
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
            (out_dir / name).write_text(text, encoding="utf-8", newline="\n")
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
        verify_registry_catalog(_REGISTRY, args.trust)
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
        target.write_text(content, encoding="utf-8", newline="\n")
    copied = copy_web_assets(web_assets, out_dir) if web_assets else []
    print(f"[OK] 发现页已生成：{out_dir}（{len(pages)} 个页面；站点资产 {len(copied)} 个）")
    return 0
