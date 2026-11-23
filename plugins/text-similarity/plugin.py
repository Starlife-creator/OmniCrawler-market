"""文本相似度与变更检测插件：判断两次采集的内容「是不是实质变了」。

## 为什么需要

`diff-report` 只做**字段级**比较：`price` 从 199 变 299、`title` 变了。
但真实场景里更常见的是**长文本的细微变化**：

* 正文改了三个字 → 整篇被判「完全变了」，下游收到无意义告警；
* 页面只换了广告位/推荐位 → 抓下来的正文其实没变，却被当新内容入库。

需要的是「**相似度**」而不是「相等/不等」。

## 设计

用标准库 `difflib.SequenceMatcher`（零第三方依赖），对每对文本算
`ratio()`（0-1）。按阈值分三档：

| 判定 | 含义 | 典型动作 |
|---|---|---|
| `identical` | 完全相同 | 跳过（省钱） |
| `minor` | 相似但未超阈值 | 记录为「微调」，不告警 |
| `changed` | 低于阈值 | 当真变更处理 |

**为什么不用 difflib 的 `quick_ratio()`**：它在大文本上比 `ratio()` 快，
但对「顺序调换」不敏感，会高估相似度。正文场景宁可慢一点也要准。

## 契约约束

运行于隔离沙箱子进程，**不能 import omnicrawler**；只用标准库。
纯函数、无 IO。
"""
from __future__ import annotations

import difflib

PLUGIN_METADATA = {
    "name": "text-similarity",
    "version": "1.0.0",
    "description": "比较两次采集的文本相似度，区分「相同/微调/实质变更」三档",
    "plugin_types": ["processor", "transformer"],
    "permissions": [],
    "license": "MIT",
    "execution_mode": "subprocess",
}

#: 默认阈值：>=0.995 视为相同；>=0.85 视为微调（可按语料调整）。
DEFAULT_IDENTICAL = 0.995
DEFAULT_MINOR = 0.85


def _normalize(text: str) -> str:
    """折叠空白。

    抓下来的正文常因排版换行/缩进不同而"看起来变了"，实际内容一致。
    把连续空白折成单空格可消除这类噪声，**但不改变词序与标点**。
    """
    return " ".join(str(text or "").split())


def similarity(left: str, right: str) -> float:
    """两段文本的相似度（0-1）。空 vs 空算 1.0，空 vs 非空算 0.0。"""
    a, b = _normalize(left), _normalize(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def classify(
    ratio: float, *, identical: float = DEFAULT_IDENTICAL, minor: float = DEFAULT_MINOR
) -> str:
    """把相似度映射成三档标签。"""
    if ratio >= identical:
        return "identical"
    if ratio >= minor:
        return "minor"
    return "changed"


def compare_text(
    before: str,
    after: str,
    *,
    identical: float = DEFAULT_IDENTICAL,
    minor: float = DEFAULT_MINOR,
) -> dict:
    """比较一对文本，返回结构化结论。"""
    ratio = similarity(before, after)
    verdict = classify(ratio, identical=identical, minor=minor)
    return {
        "ratio": round(ratio, 6),
        "verdict": verdict,
        "changed": verdict == "changed",
        "before_len": len(_normalize(before)),
        "after_len": len(_normalize(after)),
    }


def handle(operation, payload):
    """契约 2 入口。

    * `processor.similarity`：比一对（`before` / `after`）；
    * `processor.similarity-pairs`：比多对（`pairs: [{key, before, after}]`）。
    """
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    try:
        identical = float(config.get("identical") or DEFAULT_IDENTICAL)
    except (TypeError, ValueError):
        identical = DEFAULT_IDENTICAL
    try:
        minor = float(config.get("minor") or DEFAULT_MINOR)
    except (TypeError, ValueError):
        minor = DEFAULT_MINOR

    if operation == "processor.similarity":
        result = compare_text(
            payload.get("before", ""), payload.get("after", ""),
            identical=identical, minor=minor,
        )
        result["summary"] = (
            f"相似度 {result['ratio']:.3f} -> {result['verdict']}"
        )
        return result

    if operation == "processor.similarity-pairs":
        rows = []
        counts = {"identical": 0, "minor": 0, "changed": 0}
        for pair in payload.get("pairs") or []:
            if not isinstance(pair, dict):
                continue
            one = compare_text(
                pair.get("before", ""), pair.get("after", ""),
                identical=identical, minor=minor,
            )
            one["key"] = pair.get("key", "")
            counts[one["verdict"]] += 1
            rows.append(one)
        return {
            "results": rows,
            "counts": counts,
            "summary": (
                f"共 {len(rows)} 对：相同 {counts['identical']}、"
                f"微调 {counts['minor']}、实质变更 {counts['changed']}"
            ),
        }

    return {"operation": operation}
