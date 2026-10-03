"""OmniCrawler 官方需求清单：只读浏览仓库开放 Issues（P2.2，§10.4）。

数据经宿主 ``network.fetch``（egress 策略与日配额约束、密钥零暴露）拉取
GitHub 公开 API；无本地凭据、无写入、无遥测。UI 全部走声明式视图
（rich_text + resource_list），由宿主渲染——本插件不触碰任何 Qt 对象。
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, UTC
from typing import Any

import omnicrawler_sdk

PLUGIN_METADATA = {
    "name": "issue-wishlist",
    "version": "1.1.0",
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

MAX_PAGES = 5
PAGE_SIZE = 30
REFRESH_INTERVAL = 30
_state: dict[str, Any] = {"issues": [], "error": "", "fetched": False,
    "updated_at": "", "last_attempt": None, "retry_after": 0.0,
    "complete": False, "query": "", "label": "all", "selected": ""}


def _components() -> list[dict]:
    if _state["error"]:
        segments = [{"type": "heading", "text": "需求清单"},
            {"type": "paragraph", "text": f"上次刷新失败：{_state['error']}；保留上次成功数据。"}]
    elif not _state["fetched"]:
        segments = [{"type": "heading", "text": "需求清单"},
            {"type": "paragraph", "text": "只读展示仓库开放 Issues，点“刷新”加载。"}]
    else:
        segments = [{"type": "heading", "text": f"开放 Issues（{len(_state['issues'])}）"},
            {"type": "paragraph", "text": "点击条目后使用下方链接到 GitHub 查看或参与讨论。"}]
    if _state["updated_at"]:
        segments.append({"type": "paragraph", "text": f"上次成功刷新：{_state['updated_at']}；" + ("已读取全部当前结果" if _state["complete"] else "达到分页上限，结果可能不完整")})
    query = _state["query"].casefold()
    visible = [i for i in _state["issues"] if (not query or query in i["title"].casefold() or query in str(i["number"])) and (_state["label"] == "all" or _state["label"] in i.get("labels", []))]
    components = [{"type": "rich_text", "id": "intro", "segments": segments},
        {"type": "button", "id": "refresh", "label": "刷新", "action": "refresh"},
        {"type": "resource_list", "id": "issues", "label": "Issues", "items": [
            {"id": str(i["number"]), "label": f"#{i['number']} {i['title']}", "subtitle": " · ".join(i.get("labels", [])) or i["state"]} for i in visible],
            "empty_text": "无匹配条目；可刷新或调整筛选", "action": "open-issue"},
        {"type": "text", "id": "search", "label": "搜索标题 / 编号", "value": _state["query"], "maxlength": 200, "action": "search"},
        {"type": "select", "id": "label-filter", "label": "标签", "value": _state["label"], "action": "filter-label",
            "options": [{"label": "全部", "value": "all"}] + [{"label": t, "value": t} for t in sorted({t for i in _state["issues"] for t in i.get("labels", [])})[:50]]}]
    selected = next((i for i in _state["issues"] if str(i["number"]) == _state["selected"]), None)
    if selected:
        components.append({"type": "rich_text", "id": "selected-issue", "segments": [{"type": "link", "text": f"在 GitHub 打开 #{selected['number']}", "url": selected["html_url"]}]})
    return components


def _view() -> dict:
    return {"view_id": "issue-wishlist.main", "title": "需求清单", "preferred_zone": "right",
        "movable": True, "resizable": True, "floatable": True, "default_width": 400,
        "default_height": 640, "minimum_width": 280, "minimum_height": 320, "components": _components()}


def _fetch_issues() -> None:
    now = time.monotonic()
    if now < _state["retry_after"]:
        _state["error"] = "GitHub API 限流，请稍后重试"
        return
    if _state["last_attempt"] is not None and now - _state["last_attempt"] < REFRESH_INTERVAL:
        _state["error"] = "刷新间隔至少 30 秒，请稍后再试"
        return
    _state["last_attempt"] = now
    issues, seen = [], set()
    complete = False
    for page in range(1, MAX_PAGES + 1):
        url = REPO_ISSUES_URL + f"&page={page}"
        response = omnicrawler_sdk.call("network.fetch", {"url": url})
        status = int(response.get("status", 0))
        if status != 200:
            _state["error"] = f"GitHub API 返回 {status}"
            if status in {403, 429}:
                _state["retry_after"] = time.monotonic() + 60
                _state["error"] += "；可能达到配额或访问受限，至少等待 60 秒"
            return
        body = base64.b64decode(str(response.get("body_b64", "")), validate=True)
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, list):
            raise ValueError("GitHub 返回了无效列表")
        for item in data:
            if not isinstance(item, dict) or "pull_request" in item:
                continue
            number = item.get("number")
            if isinstance(number, bool) or not isinstance(number, int) or number <= 0 or number in seen:
                continue
            seen.add(number)
            issues.append({"number": number, "title": str(item.get("title") or "无标题")[:200],
                "state": str(item.get("state", "open")),
                "html_url": f"https://github.com/Starlife-creator/omnicrawler/issues/{number}",
                "labels": [str(t.get("name", ""))[:80] for t in item.get("labels", []) if isinstance(t, dict) and t.get("name")]})
        if len(data) < PAGE_SIZE:
            complete = True
            break
    # Publish only a fully successful bounded refresh; failures leave the old list intact.
    _state.update(issues=issues, error="", fetched=True, complete=complete,
        updated_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"))


def handle(operation: str, payload: dict) -> dict:
    if operation == "view.describe":
        return {"view": _view()}
    if operation != "view.action":
        return {"handled": False}
    action = str(payload.get("action", ""))
    value = payload.get("payload") or {}
    value = value if isinstance(value, dict) else {}
    if action == "refresh":
        try:
            _fetch_issues()
        except Exception:
            _state["error"] = "网络或响应解析失败，请稍后重试"
        message = f"已刷新：{len(_state['issues'])} 个开放 Issues" if not _state["error"] else f"刷新失败：{_state['error']}"
        return {"view": _view(), "message": message}
    if action == "search":
        _state["query"] = str(value.get("value") or "")[:200]
        return {"view": _view()}
    if action == "filter-label":
        label = str(value.get("value") or "all")
        allowed = {"all"} | {t for i in _state["issues"] for t in i.get("labels", [])}
        if label in allowed:
            _state["label"] = label
        return {"view": _view()}
    if action == "open-issue":
        number = str(value.get("item_id", ""))
        match = next((i for i in _state["issues"] if str(i["number"]) == number), None)
        if match is None:
            return {"message": "条目已过期，请刷新"}
        _state["selected"] = number
        return {"view": _view(), "message": f"{match['title']}\n{match['html_url']}"}
    return {"handled": False}
