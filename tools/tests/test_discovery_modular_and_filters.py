# SPDX-License-Identifier: MIT
"""发现页模块化包结构（tools/discovery/）、标签胶囊筛选、无障碍排序控件与确定性构建回归测试。"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import discovery
import generate_discovery_page as legacy_entry
from discovery import _css, _js, _pages
from discovery import build as discovery_build

_REGISTRY = Path(__file__).resolve().parents[2]


def _multi_entry_catalog(*, with_tags: bool = True, hostile: bool = False) -> dict:
    p1_tags = ['<script>alert("tag")</script>', 'a|b,"c"'] if hostile else (["PDF", "学术"] if with_tags else [])
    p2_tags = ['"><svg/onload=alert(2)>'] if hostile else (["pdf", "抽取"] if with_tags else [])
    t1_tags = ["论坛", "学术"] if with_tags and not hostile else []
    return {
        "schema_version": 1,
        "generated_at": "2026-11-18T00:00:00+00:00",
        "sequence": 100,
        "publisher": "starlife",
        "trust_model": "dual-rail-ed25519",
        "official_publishers": ["starlife"],
        "trust_public_key_ref": "keys/plugin_trust.pub.pem",
        "plugins": [
            {
                "id": "zeta-downloader",
                "name": 'Zeta 下载器 <img src=x onerror=alert(9)>' if hostile else "Zeta 论文下载器",
                "version": "1.2.0",
                "publisher": "starlife",
                "category": "utility",
                "plugin_types": ["source"],
                "summary": "批量下载开放获取文献",
                "tags": p1_tags,
                "permissions": ["network:scoped", "files:read"],
                "compatible_core": ">=1.0.0",
                "license": "MIT",
                "updated_at": "2026-11-10",
            },
            {
                "id": "alpha-extractor",
                "name": "Alpha 解析台",
                "version": "2.0.0",
                "publisher": "starlife",
                "category": "processor",
                "plugin_types": ["processor"],
                "summary": "结构化表格解析",
                "tags": p2_tags,
                "permissions": [],
                "compatible_core": ">=1.0.0",
                "license": "Apache-2.0",
                "updated_at": "2026-11-15",
            },
        ],
        "templates": [
            {
                "id": "sites/market/demo-scholar",
                "name": "Beta 学术检索模板",
                "version": "1.0.0",
                "publisher": "starlife",
                "category": "sites/academic",
                "summary": "按关键词采集公开论文目录",
                "tags": t1_tags,
                "compatible_core": ">=1.0.0",
                "license": "MIT",
                "updated_at": "2026-11-12",
                "template_file": "templates/demo/template.yaml",
            }
        ],
        "components": [
            {
                "id": "ocr-pack",
                "name": "Gamma OCR 语言包",
                "version": "1.0.0",
                "publisher": "starlife",
                "recipe_file": "components/ocr-pack/recipe.json",
                "recipe_digest": "a" * 64,
                "platforms": ["linux"] if with_tags else [],
                "architectures": ["x86_64"],
                "entry": {
                    "path": "tessdata/eng.traineddata",
                    "protocol": "ocr-file-v1",
                    "engine": "tesseract" if with_tags else "",
                },
                "artifacts": [{"url": "https://github.com/Starlife-creator/OmniCrawler-market/raw/main/x", "sha256": "b" * 64, "size": 2048}],
                "declared_total_bytes": 2048,
                "updated_at": "2026-11-16",
            }
        ],
    }


def test_discovery_package_submodules_and_legacy_reexports_aligned() -> None:
    assert hasattr(_css, "_CSS") and "tag-bar" in _css._CSS
    assert hasattr(_js, "_JS_THEME") and hasattr(_js, "_JS_LIST") and hasattr(_js, "_JS_DETAIL")
    assert hasattr(_pages, "_index_page") and hasattr(_pages, "_list_page") and hasattr(_pages, "_detail_page")
    assert hasattr(discovery_build, "build_site") and hasattr(discovery_build, "main")

    for symbol in (
        "build_site",
        "render",
        "copy_web_assets",
        "main",
        "markdown_to_html",
        "_esc",
        "_permission_risk",
        "_badges",
        "_safe_page_path",
        "_WEB_ASSET_FILES",
        "_WEB_SNIPPET",
        "_FALLBACK_REPO",
        "_CSS",
        "_JS_LIST",
        "_JS_DETAIL",
        "_JS_THEME",
    ):
        assert getattr(legacy_entry, symbol) is getattr(discovery, symbol), f"{symbol} 未保持兼容重导出"

    entry_lines = (_REGISTRY / "tools" / "generate_discovery_page.py").read_text(encoding="utf-8").splitlines()
    assert len(entry_lines) < 120, "generate_discovery_page.py 应保持薄 CLI 与重导出壳层"


def test_tag_filter_chips_derived_sorted_and_rendered_harmoniously() -> None:
    catalog = _multi_entry_catalog(with_tags=True, hostile=False)
    pages = discovery.build_site(catalog, assets_root=_REGISTRY)
    list_html = pages["catalog.html"]
    index_html = pages["index.html"]

    # 重置胶囊「全部标签」与动态计数标签胶囊（plugins 按 id 排序后 alpha-extractor 先于 zeta-downloader，
    # 故大小写折叠合并后的展示名为首次命中的 "pdf"，计数为 2，且排在单次标签之前）
    assert 'id="tag-filters"' in list_html
    assert 'data-tag-chip="" data-tag-label="全部标签" aria-pressed="true">全部标签</button>' in list_html
    assert 'data-tag-chip="pdf" data-tag-label="pdf" aria-pressed="false">pdf<span class="tag-chip-num">2</span></button>' in list_html
    assert 'data-tag-chip="学术" data-tag-label="学术" aria-pressed="false">学术<span class="tag-chip-num">2</span></button>' in list_html
    assert list_html.index('data-tag-chip="pdf"') < list_html.index('data-tag-chip="linux"')

    # 打乱输入 plugins 顺序仍产出逐字节相同的列表页
    shuffled = _multi_entry_catalog(with_tags=True, hostile=False)
    shuffled["plugins"] = list(reversed(shuffled["plugins"]))
    assert discovery.render(shuffled, assets_root=_REGISTRY) == list_html

    # 卡片 data-tags JSON 与卡片内可点击标签胶囊均就绪
    data_tags_matches = re.findall(r'data-tags="([^"]*)"', list_html)
    assert len(data_tags_matches) == 4
    parsed_tags = [json.loads(html.unescape(raw)) for raw in data_tags_matches]
    assert ["pdf", "学术"] in parsed_tags
    assert ["linux", "tesseract"] in parsed_tags
    assert 'data-card-tag="pdf"' in list_html

    # 客户端脚本联动：胶囊切换、URL ?tag= 同步、重置按钮恢复全部标签
    assert "syncTagChips(activeTag)" in list_html
    assert "hasTag(el,activeTag)" in list_html
    assert "sp.set('tag',t)" in list_html

    # 首页热门标签直达链接与迷你卡片摘要
    assert 'href="catalog.html?tag=pdf"' in index_html
    assert 'class="mini-summary"' in index_html


def test_tag_filter_falls_back_to_categories_when_no_tags_declared() -> None:
    catalog = _multi_entry_catalog(with_tags=False, hostile=False)
    list_html = discovery.render(catalog, assets_root=_REGISTRY)

    assert 'data-tag-chip="utility"' in list_html
    assert 'data-tag-chip="processor"' in list_html
    assert 'data-tag-chip="sites/academic"' in list_html


def test_hostile_tags_and_names_in_chips_and_data_attributes_escaped() -> None:
    catalog = _multi_entry_catalog(with_tags=True, hostile=True)
    pages = discovery.build_site(catalog, assets_root=_REGISTRY)
    combined = "\n".join(pages.values())
    list_html = pages["catalog.html"]

    assert '<script>alert("tag")' not in combined
    assert "<svg/onload=alert(2)>" not in combined
    assert "<img src=x onerror=" not in combined
    assert "&lt;script&gt;alert(&quot;tag&quot;)&lt;/script&gt;" in list_html

    # 即使标签含管道符、逗号、引号或尖括号，data-tags 经实体解码后仍须为合法无碰撞 JSON 数组
    for raw_attr in re.findall(r'data-tags="([^"]*)"', list_html):
        decoded = json.loads(html.unescape(raw_attr))
        assert isinstance(decoded, list)
    assert any('a|b,"c"' in json.loads(html.unescape(m)) for m in re.findall(r'data-tags="([^"]*)"', list_html))


def test_sort_control_accessibility_options_and_card_sort_datasets() -> None:
    catalog = _multi_entry_catalog(with_tags=True, hostile=False)
    list_html = discovery.render(catalog, assets_root=_REGISTRY)

    sort_match = re.search(r'<select id="sort"[^>]*>(.*?)</select>', list_html, flags=re.DOTALL)
    assert sort_match is not None, "缺少 #sort 下拉控件"
    sort_block = sort_match.group(0)
    assert 'aria-label="排序方式"' in sort_block
    assert '<option value="order">默认排序</option>' in sort_block
    assert '<option value="name">名称 A→Z</option>' in sort_block
    assert '<option value="category">类别排序</option>' in sort_block
    assert '<option value="updated">最近更新</option>' in sort_block
    assert '<option value="version">版本最高</option>' in sort_block

    # 卡片必须具备客户端按名称/类别/默认顺序稳定排序所需的数据属性
    assert 'data-name="Zeta 论文下载器"' in list_html
    assert 'data-name="Alpha 解析台"' in list_html
    assert 'data-category="sites/academic"' in list_html
    assert "mode==='name'" in list_html
    assert "mode==='category'" in list_html


def test_deterministic_site_build_and_lf_output(tmp_path: Path) -> None:
    catalog = json.loads((_REGISTRY / "catalog.json").read_text(encoding="utf-8"))
    first_pages = discovery.build_site(catalog, catalog_sha256="1" * 64, signature_sha256="2" * 64, assets_root=_REGISTRY)
    second_pages = discovery.build_site(catalog, catalog_sha256="1" * 64, signature_sha256="2" * 64, assets_root=_REGISTRY)
    assert first_pages == second_pages

    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"
    assert legacy_entry.main(["--output", str(out_a)]) == 0
    assert legacy_entry.main(["--output", str(out_b)]) == 0

    files_a = sorted(p.relative_to(out_a).as_posix() for p in out_a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(out_b).as_posix() for p in out_b.rglob("*") if p.is_file())
    assert files_a == files_b and "index.html" in files_a and "catalog.html" in files_a
    for rel in files_a:
        raw_a = (out_a / rel).read_bytes()
        raw_b = (out_b / rel).read_bytes()
        assert raw_a == raw_b, f"{rel} 两次生成字节不一致"
        assert b"\r\n" not in raw_a, f"{rel} 混入 CRLF 行尾"
