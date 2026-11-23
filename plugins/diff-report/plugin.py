"""变更对比报告插件：把两次采集结果对比成「新增/删除/修改」摘要。

## 为什么需要

增量采集的常见需求是「这次比上次变了什么」。用户真正想知道的不是
「一共 500 条」，而是「有 3 条新增、1 条改价、2 条下架」。

这个插件提供 `processor.diff` 操作：给定 `previous` 与 `current` 两组条目
（各带稳定键 `key`），产出三类差异。

## 契约约束

* 运行于**隔离沙箱子进程**，**不能 import omnicrawler**；无第三方依赖。
* 纯函数、无 IO：输入来自 payload，输出是纯数据结构。
  这样它能被单测完全覆盖，也便于在沙箱里受限运行。
"""

PLUGIN_METADATA = {
    "name": "diff-report",
    "version": "1.0.0",
    "description": "对比两次采集结果，产出新增/删除/修改三类差异摘要",
    "plugin_types": ["processor", "transformer"],
    "permissions": [],
    "license": "MIT",
    "execution_mode": "subprocess",
}


def _index(items, key_field: str) -> dict:
    """按稳定键建索引。跳过没有键的条目（它们无法对比）。"""
    out: dict[str, dict] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = item.get(key_field)
        if key is None or str(key).strip() == "":
            continue
        out[str(key)] = item
    return out


def _comparable(item: dict, ignore) -> dict:
    """取出用于判断「是否变化」的字段集。

    `ignore` 里的字段（如 `fetched_at`、`etag`）不参与比较 —— 它们每次
    采集都会变，纳入比较会让所有条目都报「修改」。
    """
    skipped = {str(x) for x in (ignore or ())}
    return {
        k: v
        for k, v in item.items()
        if k not in skipped and not str(k).startswith("_")
    }


def diff(previous, current, key_field: str = "key", ignore=None) -> dict:
    """计算两组条目的差异。**这是本插件的核心，被单测直接调用。**"""
    prev = _index(previous, key_field)
    curr = _index(current, key_field)

    added = sorted(set(curr) - set(prev))
    removed = sorted(set(prev) - set(curr))
    changed = []
    for key in sorted(set(prev) & set(curr)):
        before = _comparable(prev[key], ignore)
        after = _comparable(curr[key], ignore)
        if before != after:
            # 只报**哪些字段变了**，不整条回传（报告要能一眼读完）
            fields = sorted(
                f
                for f in set(before) | set(after)
                if before.get(f) != after.get(f)
            )
            changed.append({"key": key, "fields": fields})

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "counts": {
            "previous": len(prev),
            "current": len(curr),
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }


def summary_line(result: dict) -> str:
    """一行中文摘要，供日志/通知直接使用。"""
    c = result.get("counts") or {}
    return (
        f"对比完成：新增 {c.get('added', 0)}、删除 {c.get('removed', 0)}、"
        f"修改 {c.get('changed', 0)}（前 {c.get('previous', 0)} → 现 {c.get('current', 0)}）"
    )


def handle(operation, payload):
    """契约 2 入口。"""
    if operation != "processor.diff":
        return {"operation": operation}

    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    result = diff(
        payload.get("previous"),
        payload.get("current"),
        key_field=str(config.get("key_field") or payload.get("key_field") or "key"),
        ignore=config.get("ignore") or payload.get("ignore"),
    )
    result["summary"] = summary_line(result)
    return result
