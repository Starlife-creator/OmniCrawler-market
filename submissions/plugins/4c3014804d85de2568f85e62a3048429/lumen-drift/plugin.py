"""Lumen Drift: sandboxed local-media and Wallpaper Workshop browser."""

from __future__ import annotations

import base64
import json

import omnicrawler_sdk

PLUGIN_METADATA = {
    "name": "lumen-drift", "version": "0.3.0", "api_version": 1,
    "description": "安全发现、预览并呈现本地媒体与 Wallpaper Engine 创意工坊资源",
    "plugin_types": ["resource_provider", "view"], "category": "appearance",
    "tags": ["wallpaper", "ambient", "video", "wallpaper-engine", "declarative-ui"],
    "permissions": ["resources:read", "surfaces:background", "render:local", "render:scripted"],
    "required_capabilities": {
        "resources.enumerate": ">=1", "resources.read": ">=1",
        "render.html.snapshot": ">=1", "render.html.live.start": ">=1",
        "surface.background.set": ">=1",
    },
    "domains": [], "input_files": [], "dependencies": [], "license": "MIT",
    "execution_mode": "subprocess", "min_core_version": "0.11.2",
}

_IMAGE = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
_VIDEO = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
_HTML = {".htm", ".html"}
_state = {"handle": "", "items": [], "opacity": 24, "dim": 30, "fit": "cover", "html_mode": "snapshot"}


def _suffix(path: str) -> str:
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[-1].casefold() if "." in name else ""


def _read_json(handle: str, relative: str) -> dict:
    response = omnicrawler_sdk.call("resources.read", {
        "handle": handle, "relative": relative, "maximum_bytes": 1_048_576,
    })
    try:
        raw = base64.b64decode(response.get("content_b64", ""), validate=True)
        value = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _join(parent: str, child: str) -> str:
    parts = [str(value).replace("\\", "/").strip("/") for value in (parent, child)]
    return "/".join(value for value in parts if value)


def _scan(handle: str) -> list[dict]:
    response = omnicrawler_sdk.call("resources.enumerate", {
        "handle": handle, "relative": "", "recursive": True, "limit": 2000,
    })
    entries = [item for item in response.get("items", []) if isinstance(item, dict)]
    files = {str(item.get("relative", "")): item for item in entries if item.get("kind") == "file"}
    found, claimed = [], set()
    for relative in sorted(files, key=str.casefold):
        if relative.rsplit("/", 1)[-1].casefold() != "project.json":
            continue
        project = _read_json(handle, relative)
        parent = relative.rsplit("/", 1)[0] if "/" in relative else ""
        media = _join(parent, str(project.get("file", "")))
        if media not in files:
            continue
        suffix, kind = _suffix(media), str(project.get("type", "unknown")).casefold()
        supported = suffix in _IMAGE | _VIDEO | _HTML
        title = str(project.get("title") or parent.rsplit("/", 1)[-1] or media).strip()
        found.append({
            "id": media, "label": title[:160], "supported": supported,
            "subtitle": (f"Wallpaper Engine · {kind} · {suffix or '未知格式'}"
                         + ("" if supported else " · 当前仅展示，不可播放"))[:240],
        })
        claimed.add(media)
    for relative in sorted(files, key=str.casefold):
        if relative in claimed or _suffix(relative) not in _IMAGE | _VIDEO | _HTML:
            continue
        found.append({
            "id": relative, "label": relative.rsplit("/", 1)[-1][:160], "supported": True,
            "subtitle": "本地 HTML 快照" if _suffix(relative) in _HTML else "本地媒体",
        })
        if len(found) >= 500:
            break
    return found[:500]


def _components() -> list[dict]:
    items = [{key: item[key] for key in ("id", "label", "subtitle")} for item in _state["items"]]
    return [
        {"type": "label", "id": "safety-note", "text":
         "文件访问经用户授权句柄完成；媒体与网页快照均由 OmniCrawler 宿主渲染。"},
        {"type": "directory_picker", "id": "wallpaper-engine-folder",
         "label": "自动查找 Wallpaper Engine 文件夹", "directory_label": "Wallpaper Engine 创意工坊",
         "discovery_kind": "steam_workshop", "discovery_id": "431960", "action": "source-selected"},
        {"type": "directory_picker", "id": "manual-folder", "label": "手动选择本地资源文件夹…",
         "directory_label": "本地壁纸资源", "action": "source-selected"},
        {"type": "resource_list", "id": "wallpaper-list", "label": f"可用资源（{len(items)}）",
         "items": items, "empty_text": "尚未选择目录，或目录中没有受支持资源", "action": "play-resource"},
        {"type": "slider", "id": "opacity", "label": "背景可见度", "minimum": 5,
         "maximum": 85, "value": _state["opacity"], "action": "configure-opacity"},
        {"type": "slider", "id": "dim", "label": "暗色遮罩", "minimum": 0,
         "maximum": 85, "value": _state["dim"], "action": "configure-dim"},
        {"type": "select", "id": "fit", "label": "适配方式", "options": [
            {"label": "覆盖裁剪", "value": "cover"}, {"label": "完整包含", "value": "contain"},
            {"label": "拉伸", "value": "stretch"}], "value": _state["fit"], "action": "configure-fit"},
        {"type": "select", "id": "html-mode", "label": "HTML 渲染模式", "options": [
            {"label": "安全静态快照（禁用脚本）", "value": "snapshot"},
            {"label": "隔离动态背景（最高 5 FPS）", "value": "live"}],
         "value": _state["html_mode"], "action": "configure-html-mode"},
        {"type": "button", "id": "clear-background", "label": "停用背景", "action": "clear-background"},
    ]


def _view() -> dict:
    return {"view_id": "lumen-drift.main", "title": "Lumen Drift · 流光漂移",
            "preferred_zone": "right", "movable": True, "resizable": True, "floatable": True,
            "default_width": 400, "default_height": 680, "minimum_width": 280,
            "minimum_height": 320, "components": _components()}


def _configure(name: str, value) -> dict:
    _state[name] = int(value) if name in {"opacity", "dim"} else str(value)
    omnicrawler_sdk.call("surface.background.configure", {name: _state[name]})
    return {"view": _view()}


def _play(relative: str) -> dict:
    item = next((entry for entry in _state["items"] if entry["id"] == relative), None)
    if item is None or not item["supported"]:
        return {"message": "此 Wallpaper Engine 资源类型尚不能安全呈现"}
    if _suffix(relative) in _HTML:
        operation = (
            "render.html.live.start" if _state["html_mode"] == "live"
            else "render.html.snapshot"
        )
        rendered = omnicrawler_sdk.call(operation, {
            "handle": _state["handle"], "relative": relative,
            "width": 1280 if operation.endswith("live.start") else 1920,
            "height": 720 if operation.endswith("live.start") else 1080,
            "scripted": False,
        })
        omnicrawler_sdk.call("surface.background.set", {"render_handle": rendered["handle"]})
    else:
        omnicrawler_sdk.call("surface.background.set", {"handle": _state["handle"], "relative": relative})
    omnicrawler_sdk.call("surface.background.configure", {
        "opacity": _state["opacity"], "dim": _state["dim"], "fit": _state["fit"],
    })
    return {"message": f"已呈现：{item['label']}"}


def handle(operation: str, payload: dict) -> dict:
    if operation == "view.describe":
        return {"view": _view()}
    if operation == "resource.inventory":
        return {"count": len(_state["items"]), "items": list(_state["items"])}
    if operation == "resource.action":
        return {"handled": False}
    if operation != "view.action":
        return {"handled": False}
    action, value = str(payload.get("action", "")), payload.get("payload", {})
    value = value if isinstance(value, dict) else {}
    if action == "source-selected":
        _state["handle"] = str(value.get("resource_handle", ""))
        _state["items"] = _scan(_state["handle"])
        return {"view": _view(), "message": f"发现 {len(_state['items'])} 个可用资源"}
    if action == "play-resource":
        return _play(str(value.get("item_id", "")))
    if action == "configure-opacity":
        return _configure("opacity", value.get("value", 24))
    if action == "configure-dim":
        return _configure("dim", value.get("value", 30))
    if action == "configure-fit":
        return _configure("fit", value.get("value", "cover"))
    if action == "configure-html-mode":
        mode = str(value.get("value", "snapshot"))
        _state["html_mode"] = mode if mode in {"snapshot", "live"} else "snapshot"
        return {"view": _view()}
    if action == "clear-background":
        omnicrawler_sdk.call("surface.background.clear", {})
        return {"message": "背景已停用"}
    return {"handled": False}
