#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""签名透明日志：POSIX 归一（P3-11）+ v2 哈希链与重放校验（P2-5）+ 审核留痕（P2-11）。

- 新条目写入前经 ``canonicalize_entry`` 归一（反斜杠 → ``/``）；
- ``migrate_transparency_log`` 一次性把历史 Windows 路径改写为 POSIX；
- ``check_transparency_log`` 复核 JSON 合法、路径字段无反斜杠；
- v2 条目含 ``seq`` / ``prev_hash`` / ``entry_hash`` 哈希链，``verify_transparency_chain``
  重放校验链链接续、序号单调、条目哈希可复算；v1 旧条目作为 legacy 历史只读保留，
  不参与链计算；v2 链之后混入 v1 条目即报 schema 混存；
- 公网 Rekor 类公开账本锚定属外部配套（P2-5 跨仓/环境待落地）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 日志中承载相对路径的字段（新增路径字段须在此登记）。
PATH_FIELDS = (
    "plugin",
    "package_manifest_file",
    "creator_identity_file",
    "creator_signature_file",
    "maintainer_signature_file",
)

# v2 链条目中不参与 entry_hash 计算的元字段。
_CHAIN_META_FIELDS = {"schema_version", "seq", "prev_hash", "entry_hash"}

REVIEW_DECISIONS = {"approved", "changes_requested", "rejected"}


def canonicalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """把路径字段中的反斜杠统一替换为 POSIX 正斜杠；其余字段原样保留。"""
    out = dict(entry)
    for field in PATH_FIELDS:
        value = out.get(field)
        if isinstance(value, str):
            out[field] = value.replace("\\", "/")
    return out


def migrate_transparency_log(path: Path) -> int:
    """就地迁移历史日志：返回被改写的条目数（路径归一化）。"""
    if not path.is_file():
        return 0
    original_lines = path.read_text(encoding="utf-8").splitlines()
    rewritten: list[str] = []
    changed = 0
    for line in original_lines:
        if not line.strip():
            continue
        entry = json.loads(line)
        canonical = canonicalize_entry(entry)
        if canonical != entry:
            changed += 1
        rewritten.append(json.dumps(canonical, ensure_ascii=False, sort_keys=True) + "\n")
    path.write_text("".join(rewritten), encoding="utf-8", newline="\n")
    return changed


def check_transparency_log(path: Path) -> list[str]:
    """返回日志违规清单（空列表即通过）：JSON 非法、路径字段含反斜杠。"""
    findings: list[str] = []
    if not path.is_file():
        return findings
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            findings.append(f"第 {lineno} 行 JSON 非法: {exc}")
            continue
        if not isinstance(entry, dict):
            findings.append(f"第 {lineno} 行不是映射")
            continue
        for field in PATH_FIELDS:
            value = entry.get(field)
            if isinstance(value, str) and "\\" in value:
                findings.append(f"第 {lineno} 行 {field} 含反斜杠路径: {value}")
    return findings


def _canonical_json(entry: dict[str, Any]) -> str:
    return json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def entry_hash(entry: dict[str, Any]) -> str:
    """v2 条目业务字段的 SHA-256；链元字段（seq/prev_hash/entry_hash/schema_version）不计入。"""
    payload = {k: v for k, v in entry.items() if k not in _CHAIN_META_FIELDS}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def build_v2_entry(
    prev: dict[str, Any] | None,
    *,
    operation: str,
    package_id: str,
    version: str,
    creator_fingerprint: str,
    evidence_sha256: str,
    package_type: str | None = None,
    package_manifest_file: str | None = None,
    reviewer: str | None = None,
    decision: str | None = None,
    review_comment: str | None = None,
    timestamp: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造一条 v2 链条目；``prev`` 为链上一条 v2 条目（首条传 None）。"""
    if decision is not None and decision not in REVIEW_DECISIONS:
        raise ValueError(f"非法审核结论: {decision!r}（{sorted(REVIEW_DECISIONS)}）")
    body: dict[str, Any] = {
        "operation": operation,
        "package_type": package_type,
        "package_id": package_id,
        "version": version,
        "creator_fingerprint": creator_fingerprint,
        "evidence_sha256": evidence_sha256,
        "package_manifest_file": package_manifest_file,
        "reviewer": reviewer,
        "decision": decision,
        "review_comment": review_comment,
        "timestamp": timestamp or datetime.now(UTC).isoformat(timespec="seconds"),
    }
    body = {k: v for k, v in body.items() if v is not None}
    if extra:
        body.update(extra)
    seq = 0 if prev is None else int(prev["seq"]) + 1
    entry: dict[str, Any] = {
        "schema_version": 2,
        "seq": seq,
        "prev_hash": None if prev is None else prev["entry_hash"],
        **body,
    }
    entry["entry_hash"] = entry_hash(entry)
    return entry


def verify_transparency_chain(path: Path) -> list[str]:
    """重放 v2 哈希链：链链接续、序号单调、条目哈希可复算；v1 legacy 不参与链。"""
    findings: list[str] = []
    if not path.is_file():
        return findings
    prev_hash: str | None = None
    prev_seq = -1
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # JSON 非法由 check_transparency_log 报告
        if not isinstance(entry, dict):
            continue
        if entry.get("schema_version") != 2:
            if prev_hash is not None:
                findings.append(f"第 {lineno} 行 v1 旧条目混在 v2 哈希链之后（schema 混存）")
            continue
        if prev_hash is not None and entry.get("prev_hash") != prev_hash:
            findings.append(f"第 {lineno} 行 prev_hash 与上一条目不匹配（链断裂/重放）")
        seq = entry.get("seq")
        if not isinstance(seq, int) or seq != prev_seq + 1:
            findings.append(f"第 {lineno} 行 seq 非单调递增（{seq}，上一条 {prev_seq}）")
        recomputed = entry_hash(entry)
        if recomputed != entry.get("entry_hash"):
            findings.append(f"第 {lineno} 行 entry_hash 不可复算（载荷被篡改或哈希伪造）")
        prev_hash = entry.get("entry_hash")
        prev_seq = int(seq) if isinstance(seq, int) else prev_seq
    return findings


def last_v2_entry(path: Path) -> dict[str, Any] | None:
    """读取日志中最后一条 v2 条目（用于新条目链接 prev_hash）；无则 None。"""
    if not path.is_file():
        return None
    last: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if isinstance(entry, dict) and entry.get("schema_version") == 2:
            last = entry
    return last


__all__ = [
    "PATH_FIELDS",
    "canonicalize_entry",
    "migrate_transparency_log",
    "check_transparency_log",
    "entry_hash",
    "build_v2_entry",
    "verify_transparency_chain",
    "last_v2_entry",
    "REVIEW_DECISIONS",
]
