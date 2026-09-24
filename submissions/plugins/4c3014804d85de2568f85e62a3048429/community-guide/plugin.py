"""OmniCrawler 官方社区引导：外链降级版（P2.3，§10.9 #21 拍板形态）。

仓库未启用 Discussions（2026-09-20 实测 has_discussions=false）⇒ 首版按拍板
落在「外链引导」分支：纯静态引导面板（结构化链接段），**零网络**——不申请
任何网络能力，链接点击经宿主确认后由系统浏览器打开（§10.3 隔离要求）。
仓库启用 Discussions 后可升级为 API 拉取形态（需 maintenance 侧另行拍板）。
"""

from __future__ import annotations

from typing import Any

PLUGIN_METADATA = {
    "name": "community-guide",
    "version": "1.0.0",
    "api_version": 1,
    "description": "官方社区引导：仓库 Discussions / Issues / 贡献指南的外链导航",
    "plugin_types": ["view"],
    "category": "productivity",
    "tags": ["社区", "discussions", "外链", "官方", "引导"],
    "permissions": [],
    "required_capabilities": {"view.richtext": ">=1"},
    "domains": [],
    "input_files": [],
    "dependencies": [],
    "license": "MIT",
    "execution_mode": "subprocess",
    # view.richtext 于 2026-09-24 进入核心；更早的 core 会在能力协商阶段
    # fail-closed 拒载（启动插件代码前），不会半装。
    "min_core_version": "0.14.0",
}

_REPO = "https://github.com/Starlife-creator/omnicrawler"

_SEGMENTS = [
    {"type": "heading", "text": "加入 OmniCrawler 社区"},
    {
        "type": "paragraph",
        "text": "社区交流在 GitHub 上进行（当前仓库未启用应用内讨论区）。"
                "所有链接经确认后在系统浏览器打开；应用本身不登录、不发言、不持任何凭据。",
    },
    {"type": "bullet", "text": "提问与讨论：请先搜索是否有同类话题，避免重复开帖"},
    {"type": "bullet", "text": "报缺陷：附最小复现（配置片段 + 期望与实际行为）"},
    {"type": "bullet", "text": "提需求：说明使用场景与期望效果，需求会被收进需求清单"},
    {"type": "paragraph", "text": "常用入口："},
    {"type": "link", "text": "Discussions（讨论区）", "url": f"{_REPO}/discussions"},
    {"type": "link", "text": "Issues（缺陷与需求）", "url": f"{_REPO}/issues"},
    {"type": "link", "text": "贡献指南（CONTRIBUTING）", "url": f"{_REPO}/blob/main/CONTRIBUTING.md"},
    {"type": "link", "text": "行为准则（CODE OF CONDUCT）", "url": f"{_REPO}/blob/main/CODE_OF_CONDUCT.md"},
]


def handle(operation: str, payload: dict) -> dict:
    if operation == "view.describe":
        return {"view": _view()}
    return {"handled": False}


def _view() -> dict:
    return {
        "view_id": "community-guide.main",
        "title": "社区",
        "preferred_zone": "right",
        "movable": True,
        "resizable": True,
        "floatable": True,
        "default_width": 400,
        "default_height": 560,
        "minimum_width": 280,
        "minimum_height": 300,
        "components": [{"type": "rich_text", "id": "guide", "segments": _SEGMENTS}],
    }
