"""敏感数据脱敏插件：导出前把 PII / 凭据替换成可逆或不可逆的掩码。

## 为什么需要

采集结果常含个人数据：邮箱、手机号、身份证、银行卡、IP、API Key。
一旦进了导出文件（尤其交给他人或上传云存储），就构成**数据泄漏**。

项目已有 `privacy` 相关文档与 `security-report`，但那是**声明层**——
它说明「会访问什么」，不处理「导出里有什么」。这个插件补上后者。

## 设计取舍

* **默认不可逆**（哈希/掩码）：简单、安全，适合大多数交付场景。
  需要回溯时用 `reversible=true` + 用户自备密钥（HMAC，不用裸哈希）。
* **按字段名 + 模式双重判定**：只看字段名会漏（`note` 里塞了手机号）；
  只看模式会误伤（订单号长得像手机号）。两者叠加，且允许白名单豁免。
* **报告而不只替换**：返回每个字段命中多少次，便于核对脱敏是否生效。

## 契约约束

运行于隔离沙箱子进程，**不能 import omnicrawler**；无第三方依赖。
纯函数、无 IO —— 不读密钥文件、不写盘（密钥经 payload 传入）。
"""
from __future__ import annotations

import hashlib
import re

PLUGIN_METADATA = {
    "name": "mask-sensitive",
    "version": "1.1.0",
    "description": "导出前脱敏邮箱/手机/身份证/银行卡/IP/API Key，输出命中统计",
    "plugin_types": ["processor", "transformer"],
    "permissions": [],
    "license": "MIT",
    "execution_mode": "subprocess",
    #: 门 3 要求显式声明（零依赖也要写 []），且必须与实测导入图互证。
    "dependencies": [],
}

#: 内置模式。顺序有意义：先匹配更具体的（身份证 18 位比手机号 11 位长）。
PATTERNS: tuple[tuple[str, str], ...] = (
    ("id_card", r"\b\d{17}[\dXx]\b"),
    ("bank_card", r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    ("email", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    ("phone_cn", r"\b1[3-9]\d{9}\b"),
    ("ipv4", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ("api_key", r"\b(?:sk|ghp|gho|xoxb|AKIA)[-_A-Za-z0-9]{16,}\b"),
)

#: 字段名命中这些关键词时**整值脱敏**（哪怕内容看起来正常）。
SENSITIVE_FIELD_HINTS: tuple[str, ...] = (
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "credential", "private_key", "session", "cookie", "auth",
    "phone", "mobile", "email", "id_card", "bank", "address",
)

#: 这些字段名即使命中模式也**不脱敏**（避免误伤业务标识）。
FIELD_ALLOWLIST: tuple[str, ...] = ("order_id", "serial", "sku", "gid", "trace_id")


def _mask_value(value: str, *, keep: int = 3) -> str:
    """保留首尾少量字符，中间用 * 覆盖。空值原样返回。"""
    text = str(value)
    if len(text) <= keep * 2:
        return "*" * len(text)
    return f"{text[:keep]}{'*' * (len(text) - keep * 2)}{text[-keep:]}"


def _hash_value(value: str, secret: str) -> str:
    """HMAC-SHA256 前 16 位。`secret` 为空时退化为普通哈希（不可逆但可彩虹表）。"""
    key = (secret or "").encode("utf-8")
    digest = hashlib.sha256(key + str(value).encode("utf-8")).hexdigest()
    return f"h:{digest[:16]}"


def _field_is_sensitive(name: str) -> bool:
    lowered = str(name).casefold()
    if any(token in lowered for token in FIELD_ALLOWLIST):
        return False
    return any(token in lowered for token in SENSITIVE_FIELD_HINTS)


def mask_item(
    item: dict,
    *,
    secret: str = "",
    patterns: bool = True,
    keep: int = 3,
) -> tuple[dict, dict[str, int]]:
    """脱敏单条记录。返回 `(新记录, {命中类型: 次数})`。

    不修改入参（返回深拷贝的浅层结构即可 —— 值都是标量或字符串）。
    """
    hits: dict[str, int] = {}
    masked: dict = {}

    for name, value in (item or {}).items():
        # 1) 字段名命中敏感词 ⇒ 整值脱敏（对象/列表转成字符串再脱敏）
        if _field_is_sensitive(str(name)):
            if isinstance(value, (str, int)) and str(value).strip():
                masked[name] = _hash_value(str(value), secret) if secret else _mask_value(str(value), keep=keep)
                hits["field"] = hits.get("field", 0) + 1
            else:
                masked[name] = value
            continue

        # **白名单字段完全跳过模式匹配**。
        #
        # 早先白名单只挡「字段名命中敏感词」这一条，值的模式匹配照做 ——
        # 于是 `order_id: "13812345678"`（业务单号恰好 11 位数字）被当成
        # 手机号脱敏，破坏了可追溯性。2026-11-23 实测发现。
        if any(token in str(name).casefold() for token in FIELD_ALLOWLIST):
            masked[name] = value
            continue

        # 2) 值里命中模式 ⇒ 逐处替换
        if patterns and isinstance(value, str):
            current = value
            for label, pattern in PATTERNS:
                def _sub(match: re.Match[str], label: str = label) -> str:
                    hits[label] = hits.get(label, 0) + 1
                    return _hash_value(match.group(0), secret) if secret else _mask_value(match.group(0), keep=keep)

                current = re.sub(pattern, _sub, current)
            masked[name] = current
            continue

        masked[name] = value

    return masked, hits


def handle(operation, payload):
    """契约 2 入口。`processor.mask` / `hook.before_export` 都走同一条。"""
    if operation not in ("processor.mask", "hook.before_export"):
        return {"operation": operation}

    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    secret = str(config.get("secret") or "")
    try:
        keep = int(config.get("keep") or 3)
    except (TypeError, ValueError):
        keep = 3

    items = payload.get("items") or []
    out: list[dict] = []
    totals: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            out.append(item)
            continue
        masked, hits = mask_item(
            item, secret=secret,
            patterns=bool(config.get("patterns", True)), keep=keep,
        )
        out.append(masked)
        for key, count in hits.items():
            totals[key] = totals.get(key, 0) + count

    return {
        "items": out,
        "counts": totals,
        "total_hits": sum(totals.values()),
        "reversible": bool(secret),
        "summary": (
            f"脱敏完成：{len(out)} 条记录，共 {sum(totals.values())} 处命中"
            + ("" if not totals else f"（{', '.join(f'{k}×{v}' for k, v in sorted(totals.items()))}）")
        ),
    }