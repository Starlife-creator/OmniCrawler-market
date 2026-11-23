"""CSV 导出/导入插件：**Excel 与命令行都能正确打开的中文 CSV**。

## 为什么需要（不只是「用标准库写的」这么简单）

标准库 `csv` 完全够用，但爬虫导出的 CSV 有两个真实坑：

### 坑 1：Excel 打开中文 CSV 是乱码

Excel（Windows 中文版）默认按 **GBK** 打开 `.csv`，而 Python 写出的是
UTF-8 无 BOM —— 于是「商品名称」变成「鍟嗗搧鍚嶇О」。

修法：**写 UTF-8 BOM**（`utf-8-sig`）。Excel 认 BOM，命令行工具也认。
这是「同一个文件既要给 Excel 又要给脚本用」的唯一解。

### 坑 2：字段里的换行/逗号/引号破坏结构

正文常含换行。手写 `",".join()` 会直接把表格拆坏。
标准库 `csv` 的 `QUOTE_MINIMAL` 会正确处理，但**前提是走它而不是手拼**。

### 坑 3：公式注入

以 `=`、`+`、`-`、`@` 开头的单元格会被 Excel 当公式执行。
恶意站点的标题写 `=HYPERLINK("http://evil","click")` 就能在用户打开时外联。
这里默认加前缀 `'` 转义（可用 `sanitize=False` 关掉）。

## 契约约束

运行于隔离沙箱子进程，**不能 import omnicrawler**；只用标准库。
纯函数、无 IO —— 返回文本，写文件由宿主负责。
"""
from __future__ import annotations

import csv
import io

PLUGIN_METADATA = {
    "name": "csv-io",
    "version": "1.0.0",
    "description": "导出/导入 CSV，UTF-8 BOM 兼容 Excel，并防公式注入",
    "plugin_types": ["exporter", "processor"],
    "permissions": [],
    "license": "MIT",
    "execution_mode": "subprocess",
}

#: 会被 Excel 当公式的起始字符。
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_cell(value: object) -> str:
    """防公式注入：以公式字符开头的值前面加 `'`。"""
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_PREFIXES:
        return "'" + text
    return text


def _collect_fieldnames(items: list[dict]) -> list[str]:
    """按**首次出现顺序**收集字段名（保持稳定，便于 diff）。"""
    seen: dict[str, None] = {}
    for item in items:
        for key in item:
            seen.setdefault(str(key), None)
    return list(seen)


def to_csv(
    items: list[dict],
    *,
    fields: list[str] | None = None,
    bom: bool = True,
    sanitize: bool = True,
) -> dict:
    """把记录列表转成 CSV 文本。

    返回 `{text, count, fields}`。`text` **包含 BOM**（当 `bom=True`）。
    """
    fieldnames = [str(f) for f in (fields or _collect_fieldnames(items))]
    if not fieldnames:
        return {"text": "", "count": 0, "fields": []}

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\r\n"
    )
    writer.writeheader()
    count = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        row = {
            key: (_sanitize_cell(item.get(key)) if sanitize else ("" if item.get(key) is None else str(item.get(key))))
            for key in fieldnames
        }
        writer.writerow(row)
        count += 1

    text = buffer.getvalue()
    if bom:
        # Excel 靠 BOM 判定 UTF-8；命令行工具（jq/python）也能正确跳过它。
        text = "\ufeff" + text
    return {"text": text, "count": count, "fields": fieldnames}


def from_csv(text: str) -> dict:
    """解析 CSV 文本，返回 `{items, fields}`。

    自动容忍 BOM（`utf-8-sig` 写出的文件读回来带 `\ufeff`）。
    """
    cleaned = (text or "").lstrip("\ufeff")
    if not cleaned.strip():
        return {"items": [], "fields": []}
    reader = csv.DictReader(io.StringIO(cleaned))
    items = [dict(row) for row in reader]
    return {"items": items, "fields": list(reader.fieldnames or [])}


def handle(operation, payload):
    """契约 2 入口。"""
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}

    if operation == "exporter.csv":
        result = to_csv(
            payload.get("items") or [],
            fields=config.get("fields") or payload.get("fields"),
            bom=bool(config.get("bom", True)),
            sanitize=bool(config.get("sanitize", True)),
        )
        result["media_type"] = "text/csv; charset=utf-8"
        result["extension"] = "csv"
        result["summary"] = f"导出 {result['count']} 行 × {len(result['fields'])} 列"
        return result

    if operation == "processor.csv-parse":
        result = from_csv(payload.get("text") or "")
        result["summary"] = f"解析 {len(result['items'])} 行 × {len(result['fields'])} 列"
        return result

    return {"operation": operation}
