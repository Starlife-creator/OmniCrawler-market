"""字段别名归一插件：把不同站点/语言的同义列名统一成一套。

## 为什么需要

同一次跨站采集里，「商品名」可能叫 `标题`、`名称`、`title`、`product_name`。
合并多个来源时，下游拿到的是**四列**，每列都只有一部分行有值。
用户要的不是"再写一次脚本"，而是「按我说的别名表归一下」。

这个插件提供 `processor.alias`：给定条目列表与别名表（`目标名 -> [别名...]`），
把同义列合并成一列。

## 三条判据（都刻意保守）

1. **只合并同一目标名下的别名**，不做模糊匹配 —— 「卡片标题」和「正文」是两回事，
   猜错比不做更糟。
2. **冲突不静默取舍**：同一行里两个别名都有值且**不相等**时，保留**第一个非空**，
   并把冲突写进 `conflicts`；调用方能看见"这里有两个值，我选了哪个"。
3. **原列不删**（默认），除非显式 `drop_source=True` —— 用户能回查原始数据。

## 契约约束

* 运行于**隔离沙箱子进程**，**不能 import omnicrawler**；无第三方依赖。
* 纯函数、无 IO：输入来自 payload，输出是纯数据结构。
"""

PLUGIN_METADATA = {
    "name": "field-alias",
    "version": "1.0.0",
    "description": "按别名表把同义列合并成一列，冲突逐行如实回报",
    "plugin_types": ["processor", "transformer"],
    "permissions": [],
    "license": "MIT",
    "execution_mode": "subprocess",
    #: 门 3 要求显式声明（零依赖也要写 []），且必须与实测导入图互证。
    "dependencies": [],
}


def _is_blank(value) -> bool:
    """空白判定：None / 空串 / 纯空白 / 空列表都算"没有值"。"""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _normalize_spec(spec) -> dict:
    """把别名表规范成 `{目标名: [别名, ...]}`（保持声明顺序、去重、去掉目标名自身）。"""
    normalized: dict = {}
    if not isinstance(spec, dict):
        return normalized
    for target, aliases in spec.items():
        name = str(target).strip()
        if not name:
            continue
        if isinstance(aliases, str):
            candidates = [aliases]
        elif isinstance(aliases, (list, tuple, set)):
            candidates = [str(item) for item in aliases]
        else:
            continue
        ordered: list = []
        for candidate in candidates:
            text = str(candidate).strip()
            if text and text != name and text not in ordered:
                ordered.append(text)
        normalized[name] = ordered
    return normalized


def apply_aliases(items, spec, *, drop_source: bool = False) -> dict:
    """按别名表合并列。**这是核心，被单测直接调用。**"""
    table = _normalize_spec(spec)
    if not table:
        return {"items": list(items or []), "renamed": {}, "conflicts": [], "dropped": []}

    renamed: dict = {}
    conflicts: list = []
    dropped: set = set()
    out: list = []

    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            out.append(item)
            continue
        row = dict(item)
        for target, aliases in table.items():
            present = [alias for alias in aliases if alias in row and not _is_blank(row.get(alias))]
            if len(present) > 1:
                # 多个别名同时有值 ⇒ 保留第一个非空，其余值如实写进 conflicts
                values = {alias: row.get(alias) for alias in present}
                distinct = {repr(value) for value in values.values()}
                if len(distinct) > 1:
                    conflicts.append({"index": index, "field": target, "values": values})
            source = present[0] if present else ""
            if source:
                if _is_blank(row.get(target)):
                    row[target] = row.get(source)
                renamed.setdefault(target, set()).add(source)
                if drop_source:
                    for alias in aliases:
                        if alias != target and alias in row:
                            row.pop(alias, None)
                            dropped.add(alias)
            elif target in row:
                # 目标列自己就有值：只需记下"它本来就是规范名"
                pass
        out.append(row)

    summary = {
        "targets": len(table),
        "merged": {key: sorted(value) for key, value in renamed.items()},
        "conflict_count": len(conflicts),
        "dropped": sorted(dropped),
    }
    return {
        "items": out,
        "renamed": summary["merged"],
        "conflicts": conflicts,
        "dropped": summary["dropped"],
        "summary": summary,
    }

def summary_line(result: dict) -> str:
    """一行中文摘要，供日志/通知直接使用。"""
    summary = result.get("summary") or {}
    merged = summary.get("merged") or {}
    conflict_count = int(summary.get("conflict_count") or 0)
    text = f"别名归一完成：合并 {len(merged)} 个目标列"
    if conflict_count:
        text += f"；{conflict_count} 处取值冲突已如实回报（保留每行第一个非空值）"
    return text


def handle(operation, payload):
    """契约 2 入口。"""
    if operation != "processor.alias":
        return {"operation": operation}

    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    aliases = config.get("aliases") if isinstance(config.get("aliases"), dict) else None
    if aliases is None:
        aliases = payload.get("aliases") if isinstance(payload.get("aliases"), dict) else {}
    drop_source = config.get("drop_source")
    if drop_source is None:
        drop_source = payload.get("drop_source", False)

    result = apply_aliases(payload.get("items"), aliases, drop_source=bool(drop_source))
    result["summary_text"] = summary_line(result)
    return result
