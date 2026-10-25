"""P3-2：持久单调序列号——落盘自增、一致性比对纳入 sequence、回退/重放被拒。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalog_lib.build import _existing_sequence
from catalog_lib.rules import _check_consistency


def _write_catalog(registry: Path, sequence: int) -> None:
    (registry / "catalog.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-10-25T00:00:00+00:00",
                "sequence": sequence,
                "publisher": "starlife",
                "plugins": [],
                "templates": [],
            }
        ),
        encoding="utf-8",
    )


def test_existing_sequence_reads_persisted_value(tmp_path: Path) -> None:
    _write_catalog(tmp_path, 41)
    assert _existing_sequence(tmp_path) == 41


def test_existing_sequence_falls_back_to_zero_when_missing(tmp_path: Path) -> None:
    assert _existing_sequence(tmp_path) == 0


def test_existing_sequence_falls_back_on_invalid_value(tmp_path: Path) -> None:
    (tmp_path / "catalog.json").write_text(
        json.dumps({"sequence": "stale"}), encoding="utf-8"
    )
    assert _existing_sequence(tmp_path) == 0


def test_sequence_monotonically_increments_from_persisted(tmp_path: Path) -> None:
    # 持久单调：每次发布在上一持久序号上 +1，同秒连续发布序号也不相等。
    _write_catalog(tmp_path, 41)
    first = _existing_sequence(tmp_path) + 1
    _write_catalog(tmp_path, first)
    second = _existing_sequence(tmp_path) + 1
    assert first == 42 and second == 43 and first < second


def test_consistency_includes_sequence_drift(tmp_path: Path) -> None:
    _write_catalog(tmp_path, 41)
    regenerated = {
        "schema_version": 1,
        "generated_at": "2026-10-25T01:00:00+00:00",  # 时间戳被排除
        "sequence": 42,  # 序号漂移（旧 catalog 回退/重放）必须被拒
        "publisher": "starlife",
        "plugins": [],
        "templates": [],
    }
    with pytest.raises(ValueError, match="sequence"):
        _check_consistency(tmp_path, regenerated)


def test_consistency_accepts_same_sequence_and_new_timestamp(tmp_path: Path) -> None:
    _write_catalog(tmp_path, 41)
    regenerated = {
        "schema_version": 1,
        "generated_at": "2026-10-25T01:00:00+00:00",
        "sequence": 41,
        "publisher": "starlife",
        "plugins": [],
        "templates": [],
    }
    _check_consistency(tmp_path, regenerated)  # 不抛即通过
