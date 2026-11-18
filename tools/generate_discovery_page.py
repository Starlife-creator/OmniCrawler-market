#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Web 发现页生成器（§10.12）：fail-closed 验签 catalog ⇒ 渲染三级静态站。

实现布局：核心逻辑已按职责拆分为 ``tools/discovery/`` 包：
- ``tools/discovery/_css.py``   ：内联样式表常量与主题令牌
- ``tools/discovery/_js.py``    ：客户端交互脚本（主题切换、搜索/标签胶囊/排序筛选、复制 ID）
- ``tools/discovery/_pages.py`` ：HTML 转义、受限 Markdown、M5 徽章语义与三级页面渲染辅助
- ``tools/discovery/build.py``  ：fail-closed 验签门禁、``build_site()`` 整站装配与 CLI 入口

本文件保持薄 CLI 与向后兼容重导出入口，所有历史导入路径（``check_discovery_page.py`` 与
``tools/tests/*.py``）零破坏。

用法：python tools/generate_discovery_page.py [--output _pages] [--web-assets <主仓 web 资产目录>]
"""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from discovery import (  # noqa: E402,F401
    _COMPONENT_BADGE_TEXT,
    _CSS,
    _FACTS_LIMIT,
    _FALLBACK_REPO,
    _HIGH_RISK_PERMISSIONS,
    _HOME_TAG_LIMIT,
    _ID_RE,
    _INDEX,
    _JS_DETAIL,
    _JS_LIST,
    _JS_THEME,
    _KIND_LABELS,
    _LIST,
    _LOGO_DIR,
    _MEDIUM_RISK_PERMISSIONS,
    _REGISTRY,
    _SIG_NAME,
    _TAG_CHIP_LIMIT,
    _WEB_ASSET_FILES,
    _WEB_SNIPPET,
    _badges,
    _card,
    _chips,
    _collect_catalog_tags,
    _component_category,
    _component_sections,
    _detail_page,
    _entry_category,
    _entry_tags,
    _esc,
    _facts,
    _format_bytes,
    _head_snippet,
    _index_page,
    _inline_logo,
    _is_block_start,
    _list_page,
    _md_inline,
    _official,
    _pairs,
    _permission_risk,
    _rel_prefix,
    _repo_link,
    _reviewed,
    _risk_reason,
    _safe_page_path,
    _search_blob,
    _shell,
    _site_root,
    _tag_buttons,
    _tag_filter_bar,
    _text,
    _version_key,
    build_site,
    copy_web_assets,
    main,
    markdown_to_html,
    render,
    verify_registry_catalog,
)

if __name__ == "__main__":
    raise SystemExit(main())
