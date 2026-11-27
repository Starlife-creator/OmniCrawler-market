"""JSONL 导出插件：把采集结果转成每行一条的 JSON Lines。

## 为什么需要

JSON Lines（`.jsonl`）是数据管道的通用交换格式：每行一条独立 JSON，
可以直接 `cat` 看、按行流式处理、被 `jq`/DuckDB/Spark 直接读，
也不需要把整个结果集塞进内存。相比「一个巨大 JSON 数组」，它在
大结果集上不会 OOM。

## 契约约束

* 运行于**隔离沙箱子进程**，**不能 import omnicrawler**；无第三方依赖。
* 纯函数、无 IO：输入是条目列表，输出是字符串。
  （写文件由宿主负责 —— 插件不碰文件系统，`permissions` 为空。）
"""

PLUGIN_METADATA = {
    "name": "export-jsonl",
    "version": "1.1.0",
    "description": "把采集结果导出为 JSON Lines（每行一条独立 JSON）",
    "plugin_types": ["exporter"],
    "permissions": [],
    "license": "MIT",
    "execution_mode": "subprocess",
    #: 门 3 要求显式声明（零依赖也要写 []），且必须与实测导入图互证。
    "dependencies": [],
}

#: 单行长度上限保护。超长的行在 JSONL 里几乎无法被下游工具解析，
#: 而且往往意味着上游抓到了整个 HTML 页面。默认 1 MiB。
DEFAULT_MAX_LINE_BYTES = 1024 * 1024


def _json_dumps(value) -> str:
    """序列化为紧凑 JSON。

    **不复用标准库的 `json` 是不可能的**（必须有它），但这里刻意用
    `ensure_ascii=False` —— 中文按原样输出，文件更小、可读性更好；
    下游按 UTF-8 读即可（JSONL 规范要求 UTF-8）。
    """
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def to_jsonl(items, max_line_bytes: int = DEFAULT_MAX_LINE_BYTES) -> dict:
    """把条目列表转成 JSONL 文本。

    返回 `{text, count, skipped}`：
    * `text` —— 完整的 JSONL 内容（每行一条，末尾带换行）；
    * `count` —— 实际写出的行数；
    * `skipped` —— 因超长而跳过的条目（**显式回报，不静默丢弃**）。
    """
    lines: list[str] = []
    skipped = 0
    for item in items or []:
        line = _json_dumps(item)
        if len(line.encode("utf-8")) > max_line_bytes:
            skipped += 1
            continue
        lines.append(line)
    text = "\n".join(lines)
    if text:
        text += "\n"
    return {"text": text, "count": len(lines), "skipped": skipped}


def handle(operation, payload):
    """契约 2 入口。"""
    if operation != "exporter.jsonl":
        return {"operation": operation}

    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    raw_max = config.get("max_line_bytes") or payload.get("max_line_bytes")
    try:
        max_line_bytes = int(raw_max) if raw_max else DEFAULT_MAX_LINE_BYTES
    except (TypeError, ValueError):
        max_line_bytes = DEFAULT_MAX_LINE_BYTES
    if max_line_bytes <= 0:
        max_line_bytes = DEFAULT_MAX_LINE_BYTES

    result = to_jsonl(payload.get("items"), max_line_bytes=max_line_bytes)
    result["media_type"] = "application/x-ndjson"
    result["extension"] = "jsonl"
    return result