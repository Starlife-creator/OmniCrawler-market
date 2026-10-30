"""P2-5 v2 哈希链构建/重放/篡改检测 + P2-11 审核结论留痕负样例。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalog_lib.transparency import (
    REVIEW_DECISIONS,
    build_v2_entry,
    entry_hash,
    last_v2_entry,
    verify_transparency_chain,
)


def _entry(prev: dict | None, *, seq_base: int = 0, **overrides) -> dict:
    body = dict(
        operation="finalize-package",
        package_id="demo-processor",
        version="1.0.0",
        creator_fingerprint="f" * 32,
        evidence_sha256="a" * 64,
        package_type="plugin",
    )
    body.update(overrides)
    return build_v2_entry(prev, **body)


def _write(path: Path, entries: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in entries),
        encoding="utf-8",
    )


def test_chain_linkage_and_hash_verify(tmp_path: Path) -> None:
    log = tmp_path / "signing_transparency.jsonl"
    first = _entry(None)
    second = _entry(first, version="1.1.0")
    _write(log, [first, second])
    assert verify_transparency_chain(log) == []
    assert last_v2_entry(log)["seq"] == 1


def test_tampered_body_breaks_entry_hash(tmp_path: Path) -> None:
    log = tmp_path / "signing_transparency.jsonl"
    first = _entry(None)
    second = _entry(first, version="1.1.0")
    second["operation"] = "revoked"  # 篡改业务字段但未重算 entry_hash
    _write(log, [first, second])
    findings = verify_transparency_chain(log)
    assert any("entry_hash" in finding for finding in findings)


def test_broken_prev_hash_chain_detected(tmp_path: Path) -> None:
    log = tmp_path / "signing_transparency.jsonl"
    first = _entry(None)
    second = _entry(first, version="1.1.0")
    second["prev_hash"] = "0" * 64  # 链断裂/重放
    second["entry_hash"] = entry_hash(second)
    _write(log, [first, second])
    findings = verify_transparency_chain(log)
    assert any("prev_hash" in finding for finding in findings)


def test_non_monotonic_seq_detected(tmp_path: Path) -> None:
    log = tmp_path / "signing_transparency.jsonl"
    first = _entry(None)
    second = _entry(first, version="1.1.0")
    second["seq"] = 5
    second["entry_hash"] = entry_hash(second)
    _write(log, [first, second])
    findings = verify_transparency_chain(log)
    assert any("seq" in finding for finding in findings)


def test_legacy_v1_entries_before_chain_skipped(tmp_path: Path) -> None:
    log = tmp_path / "signing_transparency.jsonl"
    legacy = {"operation": "finalize-package", "package_id": "old", "version": "0.9.0"}
    first = _entry(None)
    _write(log, [legacy, first])
    assert verify_transparency_chain(log) == []


def test_v1_entry_mixed_after_v2_chain_rejected(tmp_path: Path) -> None:
    log = tmp_path / "signing_transparency.jsonl"
    first = _entry(None)
    legacy = {"operation": "finalize-package", "package_id": "old"}
    _write(log, [first, legacy])
    findings = verify_transparency_chain(log)
    assert any("schema 混存" in finding for finding in findings)


def test_review_fields_recorded_in_v2_entry() -> None:
    entry = _entry(
        None,
        reviewer="starlife",
        decision="approved",
        review_comment="权限与依赖复核通过",
    )
    assert entry["reviewer"] == "starlife"
    assert entry["decision"] == "approved"
    assert entry["review_comment"].startswith("权限")


def test_invalid_review_decision_rejected() -> None:
    with pytest.raises(ValueError, match="非法审核结论"):
        build_v2_entry(
            None,
            operation="finalize-package",
            package_id="p",
            version="1.0.0",
            creator_fingerprint="f" * 32,
            evidence_sha256="a" * 64,
            decision="maybe",
        )


def test_review_decisions_cover_required_outcomes() -> None:
    assert REVIEW_DECISIONS == {"approved", "changes_requested", "rejected"}
