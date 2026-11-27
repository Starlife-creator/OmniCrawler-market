"""数据质量校验插件：在导出前拦下「空字段 / 重复 / 明显异常」的条目。

## 为什么需要

采集的失败常常是**静默的**：页面改版后，标题选择器失效，于是所有条目
的 `title` 都是空串 —— 采集「成功」了 500 条，实际全是废数据。
等到用户打开导出文件才发现，已经跑了几十分钟。

这个插件在导出前做一遍质量检查，把问题**当场报出来**：

* `missing` —— 必填字段为空；
* `duplicates` —— 稳定键重复（说明分页/去重逻辑有问题）；
* `suspicious` —— 字段值明显异常（如整段 HTML 被当成标题）。

## 契约约束

* 运行于**隔离沙箱子进程**，**不能 import omnicrawler**；无第三方依赖。
* 纯函数、无 IO。
* **只报告，不修改数据** —— 是否丢弃由调用方按 `fail_on` 决定。
"""

PLUGIN_METADATA = {
    "name": "validate-items",
    "version": "1.1.0",
    "description": "导出前校验条目质量：必填缺失、键重复、明显异常值",
    "plugin_types": ["processor", "hook"],
    "permissions": [],
    "license": "MIT",
    "execution_mode": "subprocess",
    #: 门 3 要求显式声明（零依赖也要写 []），且必须与实测导入图互证。
    "dependencies": [],
}

#: 被认为是「空」的值。`0` / `False` **不算空**（它们是合法数据）。
_EMPTY_VALUES = (None, "", [], {})

#: 字段值里出现这些标记，说明很可能抓到了整段 HTML 而不是纯文本。
_HTML_MARKERS = ("<html", "<div", "<script", "<!doctype")

#: 单个字段的长度上限。超过通常是抓错了整页。
DEFAULT_MAX_FIELD_CHARS = 20000


def _is_empty(value) -> bool:
    """`0` 与 `False` 是合法值，不算空。"""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return False
    return value in _EMPTY_VALUES


def validate(
    items,
    required=None,
    key_field: str = "key",
    max_field_chars: int = DEFAULT_MAX_FIELD_CHARS,
) -> dict:
    """校验条目质量，返回问题清单（不修改输入）。"""
    required = [str(x) for x in (required or ())]
    missing: list[dict] = []
    suspicious: list[dict] = []
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    total = 0

    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        total += 1

        # 1) 必填缺失
        empty_fields = [f for f in required if _is_empty(item.get(f))]
        if empty_fields:
            missing.append({"index": index, "fields": empty_fields})

        # 2) 键重复（只报一次）
        key = item.get(key_field)
        if key is not None and str(key).strip() != "":
            k = str(key)
            if k in seen:
                if k not in duplicates:
                    duplicates.append(k)
            else:
                seen[k] = index

        # 3) 明显异常：抓到整段 HTML，或字段超长
        for name, value in item.items():
            if not isinstance(value, str):
                continue
            lowered = value[:200].lower()
            if any(marker in lowered for marker in _HTML_MARKERS):
                suspicious.append(
                    {"index": index, "field": str(name), "reason": "疑似整段 HTML"}
                )
                break
            if len(value) > max_field_chars:
                suspicious.append(
                    {"index": index, "field": str(name), "reason": "字段超长"}
                )
                break

    return {
        "total": total,
        "missing": missing,
        "duplicates": duplicates,
        "suspicious": suspicious,
        "ok": not missing and not duplicates and not suspicious,
        "counts": {
            "missing": len(missing),
            "duplicates": len(duplicates),
            "suspicious": len(suspicious),
        },
    }


def handle(operation, payload):
    """契约 2 入口。

    `processor.validate` / `hook.before_export` 都走同一条校验。
    """
    if operation not in ("processor.validate", "hook.before_export"):
        return {"operation": operation}

    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    raw_max = config.get("max_field_chars")
    try:
        max_field_chars = int(raw_max) if raw_max else DEFAULT_MAX_FIELD_CHARS
    except (TypeError, ValueError):
        max_field_chars = DEFAULT_MAX_FIELD_CHARS

    result = validate(
        payload.get("items"),
        required=config.get("required") or payload.get("required"),
        key_field=str(config.get("key_field") or payload.get("key_field") or "key"),
        max_field_chars=max_field_chars,
    )
    # `fail_on` 让调用方决定哪些问题算致命（默认全部）。
    fail_on = config.get("fail_on") or ["missing", "duplicates", "suspicious"]
    fatal = any(result["counts"].get(str(k), 0) > 0 for k in fail_on)
    result["fatal"] = fatal
    return result