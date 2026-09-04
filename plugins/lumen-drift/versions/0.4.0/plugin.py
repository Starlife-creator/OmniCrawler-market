"""Lumen Drift: sandboxed local-media and Wallpaper Workshop browser."""

from __future__ import annotations

import base64
import json

import omnicrawler_sdk

PLUGIN_METADATA = {
    "name": "lumen-drift", "version": "0.4.0", "api_version": 1,
    "description": "安全发现、预览并呈现本地媒体与 Wallpaper Engine 创意工坊资源",
    "plugin_types": ["resource_provider", "view"], "category": "appearance",
    "tags": ["wallpaper", "ambient", "video", "wallpaper-engine", "declarative-ui"],
    "permissions": ["resources:read", "surfaces:background", "render:local", "render:scripted"],
    "required_capabilities": {
        "resources.enumerate": ">=1", "resources.read": ">=1",
        "render.html.snapshot": ">=1", "render.html.live.start": ">=1",
        "surface.background.set": ">=2", "surface.background.configure": ">=2",
        "surface.background.capabilities": ">=1",
        "surface.background.clear": ">=1",
    },
    "domains": [], "input_files": [], "dependencies": [], "license": "MIT",
    "execution_mode": "subprocess", "min_core_version": "0.12.0",
}

_IMAGE = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
_VIDEO = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
_HTML = {".htm", ".html"}
_state = {
    "handle": "", "items": [], "selected_id": "", "opacity": 100,
    "panel_opacity": 88, "dim": 15, "blur": 4, "fit": "cover",
    "scope": "workspace", "preset": "balanced", "paused": False,
    "html_mode": "snapshot", "filter": "all", "active": False, "now_playing": "",
}


def _suffix(path: str) -> str:
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[-1].casefold() if "." in name else ""


def _read_json(handle: str, relative: str) -> dict:
    try:
        response = omnicrawler_sdk.call("resources.read", {
            "handle": handle, "relative": relative, "maximum_bytes": 1_048_576,
        })
        raw = base64.b64decode(response.get("content_b64", ""), validate=True)
        value = json.loads(raw.decode("utf-8-sig"))
    except (RuntimeError, OSError, ValueError, TypeError):
        # Metadata is optional: unreadable projects must not hide loose media.
        return {}
    return value if isinstance(value, dict) else {}


def _relative(value) -> str:
    if not isinstance(value, str):
        return ""
    value = value.replace("\\", "/")
    if (not value or len(value) > 480 or value.startswith("/") or ":" in value
            or any(ord(char) < 32 for char in value)
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        return ""
    return value


def _join(parent: str, child: str) -> str:
    parts = [str(value).replace("\\", "/").strip("/") for value in (parent, child)]
    return "/".join(value for value in parts if value)


def _scan(handle: str) -> list[dict]:
    response = omnicrawler_sdk.call("resources.enumerate", {
        "handle": handle, "relative": "", "recursive": True, "limit": 2000,
    })
    entries = [item for item in response.get("items", []) if isinstance(item, dict)]
    files = {
        _relative(item.get("relative")): item for item in entries
        if item.get("kind") == "file" and _relative(item.get("relative"))
    }
    found, claimed = [], set()
    for relative in sorted(files, key=str.casefold):
        if relative.rsplit("/", 1)[-1].casefold() != "project.json":
            continue
        project = _read_json(handle, relative)
        parent = relative.rsplit("/", 1)[0] if "/" in relative else ""
        child = _relative(project.get("file"))
        media = _join(parent, child)
        if not child or media not in files or media in claimed:
            continue
        suffix, kind = _suffix(media), str(project.get("type", "unknown")).casefold()
        supported = suffix in _IMAGE | _VIDEO | _HTML
        title = str(project.get("title") or parent.rsplit("/", 1)[-1] or media).strip() or media
        found.append({
            "id": media, "label": title[:160], "supported": supported,
            "subtitle": (f"Wallpaper Engine · {kind} · {suffix or '未知格式'}"
                         + ("" if supported else " · 当前仅展示，不可播放"))[:240],
        })
        claimed.add(media)
        if len(found) >= 500:
            break
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


def _visible_items() -> list[dict]:
    kind = _state["filter"]
    suffixes = {"image": _IMAGE, "video": _VIDEO, "html": _HTML}
    return [item for item in _state["items"] if (
        kind == "all" or (kind == "unsupported" and not item["supported"])
        or (kind in suffixes and item["supported"] and _suffix(item["id"]) in suffixes[kind])
    )]


def _components() -> list[dict]:
    items = [{key: item[key] for key in ("id", "label", "subtitle")} for item in _visible_items()]
    return [
        {"type": "label", "id": "safety-note", "text":
         "文件访问经用户授权句柄完成；媒体与网页快照均由 OmniCrawler 宿主渲染。"},
        {"type": "directory_picker", "id": "wallpaper-engine-folder",
         "label": "自动查找 Wallpaper Engine 文件夹", "directory_label": "Wallpaper Engine 创意工坊",
         "discovery_kind": "steam_workshop", "discovery_id": "431960", "action": "source-selected"},
        {"type": "directory_picker", "id": "manual-folder", "label": "手动选择本地资源文件夹…",
         "directory_label": "本地壁纸资源", "action": "source-selected"},
        {"type": "button", "id": "refresh", "label": "刷新当前目录", "action": "refresh-source"},
        {"type": "select", "id": "resource-filter", "label": "资源分类", "options": [
            {"label": "全部", "value": "all"}, {"label": "图片 / GIF", "value": "image"},
            {"label": "视频", "value": "video"}, {"label": "本地 HTML", "value": "html"},
            {"label": "不支持的项目", "value": "unsupported"}],
         "value": _state["filter"], "action": "filter-resources"},
        {"type": "label", "id": "playback-status", "text": (
            ("已暂停：" if _state["paused"] else "当前背景：") + _state["now_playing"]
            if _state["active"] else "背景已停用；选择资源开始呈现")},
        {"type": "label", "id": "scan-limits", "text":
         "每次最多枚举 2000 个目录项、显示 500 个资源；大目录请手动选择更小的子目录。"},
        {"type": "resource_list", "id": "wallpaper-list", "label":
         f"资源（显示 {len(items)} / 共 {len(_state['items'])}）",
         "items": items, "empty_text": "尚未选择目录，或当前分类没有资源", "action": "play-resource"},
        {"type": "button", "id": "previous", "label": "上一个背景", "action": "previous-resource"},
        {"type": "button", "id": "next", "label": "下一个背景", "action": "next-resource"},
        {"type": "button", "id": "pause", "label": "继续动态背景" if _state["paused"] else "暂停动态背景",
         "action": "toggle-pause"},
        {"type": "select", "id": "preset", "label": "视觉预设", "options": [
            {"label": "清晰", "value": "clear"}, {"label": "平衡", "value": "balanced"},
            {"label": "专注", "value": "focus"}, {"label": "沉浸", "value": "immersive"},
            {"label": "纯背景", "value": "solid"}], "value": _state["preset"],
         "action": "configure-preset"},
        {"type": "select", "id": "scope", "label": "背景范围", "options": [
            {"label": "整个应用客户区", "value": "application"},
            {"label": "完整工作区", "value": "workspace"},
            {"label": "当前内容画布", "value": "canvas"}], "value": _state["scope"],
         "action": "configure-scope"},
        {"type": "slider", "id": "opacity", "label": "背景可见度", "minimum": 5,
         "maximum": 100, "value": _state["opacity"], "action": "configure-opacity"},
        {"type": "slider", "id": "panel-opacity", "label": "前景面板不透明度", "minimum": 65,
         "maximum": 100, "value": _state["panel_opacity"], "action": "configure-panel-opacity"},
        {"type": "slider", "id": "dim", "label": "暗色遮罩", "minimum": 0,
         "maximum": 85, "value": _state["dim"], "action": "configure-dim"},
        {"type": "slider", "id": "blur", "label": "静态背景模糊", "minimum": 0,
         "maximum": 20, "value": _state["blur"], "action": "configure-blur"},
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
    bounds = {"opacity": (5, 100), "panel_opacity": (65, 100), "dim": (0, 85), "blur": (0, 20)}
    choices = {"scope": {"application", "workspace", "canvas"}, "fit": {"cover", "contain", "stretch"}}
    if name in bounds:
        if isinstance(value, bool) or not isinstance(value, int):
            return {"message": "设置值必须是整数"}
        low, high = bounds[name]
        if not low <= value <= high:
            return {"message": f"设置值必须介于 {low} 和 {high} 之间"}
    elif name not in choices or value not in choices[name]:
        return {"message": "不支持的显示设置"}
    omnicrawler_sdk.call("surface.background.configure", {name: value})
    _state[name] = value
    return {"view": _view()}


def _apply_preset(preset: str) -> dict:
    values = {
        "clear": (100, 90, 0, 0), "balanced": (100, 88, 15, 4),
        "focus": (72, 96, 32, 10), "immersive": (100, 74, 8, 0),
        "solid": (55, 100, 35, 8),
    }
    preset = preset if preset in values else "balanced"
    opacity, panel, dim, blur = values[preset]
    omnicrawler_sdk.call("surface.background.configure", {"preset": preset})
    _state.update({
        "preset": preset, "opacity": opacity, "panel_opacity": panel,
        "dim": dim, "blur": blur,
    })
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
    _state.update({"selected_id": relative, "active": True, "now_playing": item["label"]})
    omnicrawler_sdk.call("surface.background.configure", {
        "opacity": _state["opacity"], "panel_opacity": _state["panel_opacity"],
        "dim": _state["dim"], "blur": _state["blur"], "fit": _state["fit"],
        "scope": _state["scope"], "paused": _state["paused"],
    })
    return {"view": _view(), "message": f"已呈现：{item['label']}"}


def _step_resource(offset: int) -> dict:
    supported = [item for item in _visible_items() if item.get("supported")]
    if not supported:
        return {"message": "没有可安全呈现的资源"}
    current = next(
        (index for index, item in enumerate(supported) if item["id"] == _state["selected_id"]),
        -1 if offset > 0 else 0,
    )
    return _play(str(supported[(current + offset) % len(supported)]["id"]))


def _handle(operation: str, payload: dict) -> dict:
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
    if action in {"source-selected", "refresh-source"}:
        resource = value.get("resource_handle", "") if action == "source-selected" else _state["handle"]
        if not isinstance(resource, str) or not resource:
            return {"message": "请先选择并授权资源目录"}
        items = _scan(resource)
        if resource != _state["handle"] or not any(item["id"] == _state["selected_id"] for item in items):
            _state["selected_id"] = ""
        _state.update({"handle": resource, "items": items})
        playable = sum(bool(item["supported"]) for item in items)
        return {"view": _view(), "message": f"发现 {len(items)} 个资源，其中 {playable} 个可尝试呈现"}
    if action == "filter-resources":
        kind = value.get("value")
        if kind not in {"all", "image", "video", "html", "unsupported"}:
            return {"message": "不支持的资源分类"}
        _state["filter"] = kind
        return {"view": _view()}
    if action == "play-resource":
        return _play(str(value.get("item_id", "")))
    if action == "previous-resource":
        return _step_resource(-1)
    if action == "next-resource":
        return _step_resource(1)
    if action == "toggle-pause":
        if not _state["active"]:
            return {"message": "请先呈现一个背景"}
        paused = not _state["paused"]
        omnicrawler_sdk.call("surface.background.configure", {"paused": paused})
        _state["paused"] = paused
        return {"view": _view(), "message": "动态背景已暂停" if _state["paused"] else "动态背景已继续"}
    if action == "configure-preset":
        return _apply_preset(str(value.get("value", "balanced")))
    if action == "configure-scope":
        return _configure("scope", value.get("value", "workspace"))
    if action == "configure-opacity":
        return _configure("opacity", value.get("value", 100))
    if action == "configure-panel-opacity":
        return _configure("panel_opacity", value.get("value", 88))
    if action == "configure-dim":
        return _configure("dim", value.get("value", 15))
    if action == "configure-blur":
        return _configure("blur", value.get("value", 4))
    if action == "configure-fit":
        return _configure("fit", value.get("value", "cover"))
    if action == "configure-html-mode":
        mode = str(value.get("value", "snapshot"))
        _state["html_mode"] = mode if mode in {"snapshot", "live"} else "snapshot"
        return {"view": _view()}
    if action == "clear-background":
        omnicrawler_sdk.call("surface.background.clear", {})
        _state.update({"active": False, "now_playing": "", "selected_id": "", "paused": False})
        return {"view": _view(), "message": "背景已停用；插件仍保持启用，可再次选择资源"}
    return {"handled": False}


def handle(operation: str, payload: dict) -> dict:
    try:
        return _handle(operation, payload if isinstance(payload, dict) else {})
    except (RuntimeError, OSError, ValueError, TypeError, KeyError):
        # Do not echo broker errors: they can include private absolute paths.
        return {"view": _view(), "message":
                "操作未完成：请检查目录授权、资源是否仍存在或宿主媒体支持；可重新选择目录后重试。"}
