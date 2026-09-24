"""OmniCrawler 官方需求清单：只读浏览仓库开放 Issues（P2.2，§10.4）。

数据经宿主 ``network.fetch``（egress 策略与日配额约束、密钥零暴露）拉取
GitHub 公开 API；无本地凭据、无写入、无遥测。UI 全部走声明式视图
（rich_text + resource_list），由宿主渲染——本插件不触碰任何 Qt 对象。
"""

from __future__ import annotations

import base64
import json
from typing import Any

import omnicrawler_sdk

PLUGIN_METADATA = {
    "name": "issue-wishlist",
    "version": "1.0.0",
    "api_version": 1,
    "description": "官方需求清单：只读浏览 OmniCrawler 仓库的开放 Issues",
    "plugin_types": ["view"],
    "category": "productivity",
    "tags": ["issues", "需求清单", "roadmap", "官方", "只读"],
    "permissions": ["network:scoped"],
    "required_capabilities": {"network.fetch": ">=1", "view.richtext": ">=1"},
    "domains": ["api.github.com"],
    "input_files": [],
    "dependencies": [],
    "license": "MIT",
    "execution_mode": "subprocess",
    # view.richtext 于 2026-09-24 进入核心；更早的 core 会在能力协商阶段
    # fail-closed 拒载（启动插件代码前），不会半装。
    "min_core_version": "0.14.0",
}

REPO_ISSUES_URL = (
    "https://api.github.com/repos/Starlife-creator/omnicrawler/issues"
    "?state=open&per_page=30&sort=created&direction=desc"
)

_state: dict[str, Any] = {"issues": [], "error": "", "fetched": False}


def _components() -> list[dict]:
    if _state["error"]:
        segments = [
            {"type": "heading", "text": "需求清单"},
            {"type": "paragraph", "text": f"上次刷新失败：{_state['error']}"},
            {"type": "paragraph", "text": "请点「刷新」重试；持续失败多为网络或配额限制。"},
        ]
    elif not _state["fetched"]:
        segments = [
            {"type": "heading", "text": "需求清单"},
            {
                "type": "paragraph",
                "text": "这里只读展示 OmniCrawler 仓库的开放 Issues（ Roadmap 与需求讨论）。",
            },
            {"type": "paragraph", "text": "点「刷新」拉取最新列表。"},
        ]
    else:
        segments = [
            {"type": "heading", "text": f"开放 Issues（{len(_state['issues'])}）"},
            {
                "type": "paragraph",
                "text": "只读展示；点击条目可查看对应链接。发言请到仓库 Discussions。",
            },
        ]
    items = [
        {
            "id": str(issue["number"]),
            "label": f"#{issue['number']} {issue['title']}",
            "subtitle": f"{issue['state']} · {issue['html_url']}",
        }
        for issue in _state["issues"]
    ]
    return [
        {"type": "rich_text", "id": "intro", "segments": segments},
        {
            "type": "button", "id": "refresh", "label": "刷新", "action": "refresh",
        },
        {
            "type": "resource_list", "id": "issues", "label": "Issues",
            "items": items, "empty_text": "尚无数据——点「刷新」拉取", "action": "open-issue",
        },
    ]


def _view() -> dict:
    return {
        "view_id": "issue-wishlist.main",
        "title": "需求清单",
        "preferred_zone": "right",
        "movable": True,
        "resizable": True,
        "floatable": True,
        "default_width": 400,
        "default_height": 640,
        "minimum_width": 280,
        "minimum_height": 320,
        "components": _components(),
    }


def _fetch_issues() -> None:
    response = omnicrawler_sdk.call("network.fetch", {"url": REPO_ISSUES_URL})
    status = int(response.get("status", 0))
    body = base64.b64decode(str(response.get("body_b64", "")))
    if status != 200:
        _state["error"] = f"GitHub API 返回 {status}"
        _state["issues"] = []
        return
    payload = json.loads(body.decode("utf-8"))
    issues = []
    for item in payload if isinstance(payload, list) else []:
        if "pull_request" in item:  # GitHub API 的 PR 也出现在 issues 端点，排除
            continue
        issues.append(
            {
                "number": int(item.get("number", 0)),
                "title": str(item.get("title", ""))[:200],
                "state": str(item.get("state", "open")),
                "html_url": str(item.get("html_url", "")),
            }
        )
    _state["issues"] = issues
    _state["error"] = ""
    _state["fetched"] = True


def handle(operation: str, payload: dict) -> dict:
    if operation == "view.describe":
        return {"view": _view()}
    if operation != "view.action":
        return {"handled": False}
    action = str(payload.get("action", ""))
    value = payload.get("payload", {})
    value = value if isinstance(value, dict) else {}
    if action == "refresh":
        try:
            _fetch_issues()
        except Exception as exc:  # noqa: BLE001 - 任何异常都收敛为面板内错误文案
            _state["error"] = str(exc)[:200]
            _state["fetched"] = True
        message = (
            f"已刷新：{len(_state['issues'])} 个开放 Issues"
            if not _state["error"]
            else f"刷新失败：{_state['error']}"
        )
        return {"view": _view(), "message": message}
    if action == "open-issue":
        number = str(value.get("item_id", ""))
        match = next((i for i in _state["issues"] if str(i["number"]) == number), None)
        if match is None:
            return {"message": "条目已过期，请刷新"}
        return {"message": f"{match['title']}\n{match['html_url']}"}
    return {"handled": False}
