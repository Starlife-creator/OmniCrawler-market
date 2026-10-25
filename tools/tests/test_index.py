"""P3-7：ID→entry 索引字典构建、指纹约束解析与冲突拒绝。"""
from __future__ import annotations

import pytest

from catalog_lib.index import build_index, resolve_entry


def _entry(pkg_id: str, fingerprint: str) -> dict:
    return {"id": pkg_id, "creator_fingerprint": fingerprint, "version": "1.0.0"}


def test_build_index_lookup_by_id() -> None:
    index = build_index([_entry("alpha", "fp-a"), _entry("beta", "fp-b")])
    assert resolve_entry(index, "alpha")["version"] == "1.0.0"
    assert resolve_entry(index, "missing") is None


def test_resolve_entry_matches_creator_fingerprint() -> None:
    index = build_index([_entry("alpha", "fp-a")])
    assert resolve_entry(index, "alpha", creator_fingerprint="fp-a") is not None
    assert resolve_entry(index, "alpha", creator_fingerprint="fp-wrong") is None


def test_duplicate_id_same_fingerprint_kept_once() -> None:
    index = build_index([_entry("alpha", "fp-a"), _entry("alpha", "fp-a")])
    assert len(index) == 1


def test_duplicate_id_different_fingerprint_rejected() -> None:
    with pytest.raises(ValueError, match="索引冲突"):
        build_index([_entry("alpha", "fp-a"), _entry("alpha", "fp-b")])


def test_entry_missing_id_rejected() -> None:
    with pytest.raises(ValueError, match="缺少 id"):
        build_index([{"version": "1.0.0"}])
