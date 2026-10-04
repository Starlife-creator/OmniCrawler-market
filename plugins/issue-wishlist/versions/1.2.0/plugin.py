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
    "version": "1.2.0",
    "api_version": 1,
    "description": "官方需求清单：只读浏览 OmniCrawler 仓库的开放 Issues",
    "plugin_types": ["view"],
    "category": "productivity",
    "tags": ["issues", "需求清单", "roadmap", "官方", "只读"],
    "permissions": ["network:scoped", "state:read", "state:write"],
    "state_schema_version": 1,
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
    "complete": False, "query": "", "label": "all", "selected": "", "sort": "updated",
    "mark_filter": "all", "marks": {}, "marks_loaded": False, "persistent_marks": False}
MARK_KEY = "wishlist.marks.Starlife-creator.omnicrawler.v1"
MAX_MARKS = 1000


def _load_marks() -> None:
    if _state["marks_loaded"]:
        return
    _state["marks_loaded"] = True
    try:
        result = omnicrawler_sdk.call("state.get", {"key": MARK_KEY})
        _state["persistent_marks"] = "found" in result
        value = result.get("value") if result.get("found") else {}
        if isinstance(value, dict):
            records = value.get("marks", value)
            if not isinstance(records, dict):
                return
            order = value.get("order", list(records))
            if not isinstance(order, list):
                order = list(records)
            _state["marks"] = {k: {"favorite": v.get("favorite") is True, "read": v.get("read") is True}
                               for k in order[-MAX_MARKS:] if isinstance(k, str)
                               for v in [records.get(k)]
                               if isinstance(k, str) and len(k) <= 12 and k.isdigit() and 0 < int(k) and isinstance(v, dict)}
    except RuntimeError:
        _state["persistent_marks"] = False


def _mark(number: str, field: str, value: bool) -> None:
    _load_marks()
    marks = _state["marks"]
    item = dict(marks.pop(number, {"favorite": False, "read": False}))
    item[field] = value
    if any(item.values()):
        marks[number] = item
    while len(marks) > MAX_MARKS:
        del marks[next(iter(marks))]
    if _state["persistent_marks"]:
        try:
            saved = omnicrawler_sdk.call("state.set", {"key": MARK_KEY, "value": {"format": 1, "marks": marks, "order": list(marks)}})
            _state["persistent_marks"] = saved.get("saved") is True
        except RuntimeError:
            _state["persistent_marks"] = False


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
    visible = [i for i in visible if _state["mark_filter"] == "all" or
               (_state["mark_filter"] == "favorites" and _state["marks"].get(str(i["number"]), {}).get("favorite")) or
               (_state["mark_filter"] == "unread" and not _state["marks"].get(str(i["number"]), {}).get("read"))]
    visible.sort(key=lambda i: (i.get("updated_at" if _state["sort"] == "updated" else "created_at", ""), i["number"]), reverse=True)
    components = [{"type": "rich_text", "id": "intro", "segments": segments},
        {"type": "button", "id": "refresh", "label": "刷新", "action": "refresh"},
        {"type": "resource_list", "id": "issues", "label": "Issues", "items": [
            {"id": str(i["number"]), "label": f"#{i['number']} {i['title']}", "subtitle": ("★ " if _state["marks"].get(str(i["number"]), {}).get("favorite") else "") + ("已读 · " if _state["marks"].get(str(i["number"]), {}).get("read") else "未读 · ") + (" · ".join(i.get("labels", [])) or i["state"])} for i in visible],
            "empty_text": "无匹配条目；可刷新或调整筛选", "action": "open-issue"},
        {"type": "text", "id": "search", "label": "搜索标题 / 编号", "value": _state["query"], "maxlength": 200, "action": "search"},
        {"type": "select", "id": "label-filter", "label": "标签", "value": _state["label"], "action": "filter-label",
            "options": [{"label": "全部", "value": "all"}] + [{"label": t, "value": t} for t in sorted({t for i in _state["issues"] for t in i.get("labels", [])})[:50]]}]
    components.extend([
        {"type": "select", "id": "sort", "label": "排序", "value": _state["sort"], "action": "sort-issues",
         "options": [{"label": "最近更新", "value": "updated"}, {"label": "最新创建", "value": "created"}]},
        {"type": "select", "id": "marks", "label": "阅读筛选", "value": _state["mark_filter"], "action": "filter-marks",
         "options": [{"label": "全部", "value": "all"}, {"label": "收藏", "value": "favorites"}, {"label": "未读", "value": "unread"}]},
        {"type": "label", "id": "mark-status", "text": "收藏与已读将跨会话保存" if _state["persistent_marks"] else "收藏与已读仅本次会话有效（持久状态未启用）"},
    ])
    selected = next((i for i in _state["issues"] if str(i["number"]) == _state["selected"]), None)
    if selected:
        components.append({"type": "rich_text", "id": "selected-issue", "segments": [{"type": "link", "text": f"在 GitHub 打开 #{selected['number']}", "url": selected["html_url"]}]})
        components.extend([{"type": "button", "id": "favorite", "label": "取消收藏" if _state["marks"].get(_state["selected"], {}).get("favorite") else "收藏", "action": "toggle-favorite"},
                           {"type": "button", "id": "read", "label": "标记未读" if _state["marks"].get(_state["selected"], {}).get("read") else "标记已读", "action": "toggle-read"}])
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
                "created_at": str(item.get("created_at") or "")[:40],
                "updated_at": str(item.get("updated_at") or "")[:40],
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
        _load_marks()
        return {"view": _view()}
    if operation != "view.action":
        return {"handled": False}
    action = str(payload.get("action", ""))
    value = payload.get("payload") or {}
    value = value if isinstance(value, dict) else {}
    if action in {"sort-issues", "filter-marks"}:
        field, allowed = ("sort", {"updated", "created"}) if action == "sort-issues" else ("mark_filter", {"all", "favorites", "unread"})
        if value.get("value") in allowed:
            _load_marks()
            _state[field] = value["value"]
        return {"view": _view()}
    if action in {"toggle-favorite", "toggle-read"}:
        number = _state["selected"]
        if not any(str(i["number"]) == number for i in _state["issues"]):
            return {"message": "请先选择当前列表中的条目"}
        _load_marks()
        field = "favorite" if action == "toggle-favorite" else "read"
        _mark(number, field, not _state["marks"].get(number, {}).get(field, False))
        return {"view": _view()}
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
