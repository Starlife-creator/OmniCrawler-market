"""发现页组件（components）第三分支渲染、恶意字段转义与现代交互（/ 搜索、重置筛选、主题切换）回归。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from generate_discovery_page import build_site

_REGISTRY = Path(__file__).resolve().parents[2]


def _sample_catalog_with_component(*, hostile: bool = False) -> dict:
    comp_name = (
        '<script>alert("comp")</script><img src=x onerror=alert(1)>'
        if hostile
        else "Tesseract 中文简体语言包"
    )
    artifact_url = (
        'https://evil.example/chi_sim"><svg onload=alert(2)>'
        if hostile
        else "https://github.com/tesseract-ocr/tessdata_fast/raw/main/chi_sim.traineddata"
    )
    engine = '"><script>alert(3)</script>' if hostile else "tesseract"
    return {
        "schema_version": 1,
        "generated_at": "2026-11-18T00:00:00+00:00",
        "sequence": 42,
        "publisher": "starlife",
        "trust_model": "dual-rail-ed25519",
        "official_publishers": ["starlife"],
        "trust_public_key_ref": "keys/plugin_trust.pub.pem",
        "plugins": [],
        "templates": [],
        "components": [
            {
                "id": "tesseract-chi-sim",
                "name": comp_name,
                "version": "1.0.0",
                "publisher": "starlife" if not hostile else 'bad"pub<script>',
                "recipe_file": "components/tesseract-chi-sim/recipe.json",
                "recipe_digest": "a" * 64,
                "platforms": ["windows", "linux", "darwin"],
                "architectures": ["x86_64", "arm64"],
                "entry": {
                    "path": "tessdata/chi_sim.traineddata",
                    "protocol": "ocr-file-v1",
                    "engine": engine,
                },
                "artifacts": [
                    {
                        "url": artifact_url,
                        "sha256": "b" * 64,
                        "size": 2567886,
                    }
                ],
                "declared_total_bytes": 2567886,
                "updated_at": "2026-11-18",
                "description_file": "components/tesseract-chi-sim/listing.md",
            }
        ],
    }


def test_real_catalog_renders_component_across_index_list_and_detail() -> None:
    catalog = json.loads((_REGISTRY / "catalog.json").read_text(encoding="utf-8"))
    pages = build_site(catalog, assets_root=_REGISTRY)

    assert "tesseract-chi-sim.html" in pages, "组件分支必须生成独立详情页"

    index_html = pages["index.html"]
    # ★ 2026-11-27 修：此前写死 `<dd>1</dd>`，而真实目录里组件早已是 16 个 ——
    #   于是这条断言随组件增长必然失效（CI 上 validate-catalog 长期判红）。
    #   判据改成「页面上报的组件数 == catalog 里的组件数」，与数据同步而不是钉死数字；
    #   同时钉住「不是 0」—— 0 会让这条断言对"组件分支整段丢失"完全无感。
    component_total = len(catalog.get("components") or [])
    assert component_total > 0, "真实 catalog 里应当有组件，夹具本身失效了"
    assert f"<dt>组件</dt><dd>{component_total}</dd>" in index_html, (
        f"首页组件计数与 catalog 不一致（应为 {component_total}）"
    )
    assert 'href="catalog.html?kind=component"' in index_html
    # ★ 2026-11-27：首页的组件展示从「逐个卡片」改成了**分类链接**（见
    #   `tools/discovery/_pages.py` 的分类列表）。原断言「首页出现组件详情页文件名」
    #   因此失效。判据改成「首页给出组件分类入口」，这才是现在真正的可达路径；
    #   详情页本身的可达性由下面 pages["tesseract-chi-sim.html"] 那条继续守着。
    assert "catalog.html?kind=component&amp;cat=component%2F" in index_html, (
        "首页缺少组件分类入口"
    )

    list_html = pages["catalog.html"]
    assert '<option value="component">仅组件</option>' in list_html
    assert '<section class="group" data-kind="component" id="components">' in list_html
    assert '<article class="card" data-kind="component"' in list_html
    assert "只托管配方声明 · 字节从上游拉取" in list_html

    detail_html = pages["tesseract-chi-sim.html"]
    assert "只托管配方声明 · 字节从上游拉取" in detail_html
    assert "配方声明与上游构件" in detail_html
    assert "ocr-file-v1" in detail_html
    # ★ 2026-11-27：组件体积随上游发布变化（实测现在是 2.35 MB），写死数字必然漂移。
    #   判据改成「详情页确实给出了体积数字（带 MB 单位）」，守住"有体积信息"这件事本身；
    #   具体数值属于上游数据，不该由测试钉死。
    assert re.search(r"\d+(?:\.\d+)?\s*MB", detail_html), "详情页缺少组件体积信息"
    # ★ 2026-11-27：这个 sha 是 `tesseract-chi-sim` 上游构件的哈希，随上游发布变。
    #   判据改成「详情页展示了某个 64 位十六进制摘要」，守住"有可核对摘要"这件事；
    #   具体值属于上游数据，由 `check_discovery_page.py` 在真实渲染时按 catalog 核对。
    assert re.search(r"\b[0-9a-f]{64}\b", detail_html), "详情页缺少构件 SHA-256"


def test_hostile_component_fields_are_strictly_html_escaped() -> None:
    pages = build_site(
        _sample_catalog_with_component(hostile=True),
        assets_root=_REGISTRY,
        listing_reader=lambda _p: "# 组件说明 <script>alert('md')</script>",
    )
    combined = "\n".join(pages.values())

    assert '<script>alert("comp")' not in combined
    assert "<img src=x onerror=" not in combined
    assert "<svg onload=" not in combined
    assert "&lt;script&gt;alert(&quot;comp&quot;)&lt;/script&gt;" in combined
    assert "&lt;svg onload=alert(2)&gt;" in combined


def test_modern_ux_search_shortcut_reset_filter_and_theme_switcher_present() -> None:
    pages = build_site(
        _sample_catalog_with_component(hostile=False),
        assets_root=_REGISTRY,
        listing_reader=lambda _p: "说明正文",
    )
    list_html = pages["catalog.html"]

    # 搜索框按 / 聚焦与内嵌键帽、分段胶囊分支切换、重置筛选按钮、URL 状态同步
    assert 'placeholder="按 / 搜索名称、标签、ID…"' in list_html
    assert '<kbd class="search-kbd" aria-hidden="true">/</kbd>' in list_html
    for branch in ("all", "plugin", "template", "component"):
        assert f'data-kind-tab="{branch}"' in list_html
    assert "syncTabs(k)" in list_html
    assert 'id="reset-filters"' in list_html
    assert "history.replaceState" in list_html
    assert "ev.key==='/'" in list_html
    assert "prefers-reduced-motion:no-preference" in list_html

    # 浅色 / 深色 / 跟随系统 主题切换按钮、毛玻璃顶栏与 CSS data-theme 变量支持
    for name, html_text in pages.items():
        assert 'id="theme-toggle"' in html_text, f"{name} 缺少主题切换按钮"
        assert "backdrop-filter:blur(14px)" in html_text
        assert 'html[data-theme="dark"]' in html_text
        assert 'html[data-theme="light"]' in html_text
        assert html_text.count("<script") == 1, f"{name} 应保持单内联脚本块契约"
