"""P3-6：墓碑冲突判定规范化到 catalog ID（层级模板目录名 ``--`` ⇒ ``/``）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalog_lib.tombstones import _load_tombstones


def _write(registry: Path, rows: list[dict]) -> None:
    (registry / "tombstones.json").write_text(json.dumps(rows), encoding="utf-8")


def test_hierarchical_template_conflict_normalized_to_catalog_id(tmp_path: Path) -> None:
    # 目录名 social--market--weibo-search 对应 catalog ID social/market/weibo-search；
    # 墓碑按 catalog ID 声明也必须命中冲突，不得因分隔符不同而绕过。
    (tmp_path / "templates" / "social--market--weibo-search").mkdir(parents=True)
    _write(tmp_path, [
        {"id": "social/market/weibo-search", "removed_at": "2026-09-01", "reason": "r"},
    ])
    with pytest.raises(ValueError, match="冲突"):
        _load_tombstones(tmp_path)


def test_plugin_conflict_still_detected(tmp_path: Path) -> None:
    (tmp_path / "plugins" / "live-plugin").mkdir(parents=True)
    _write(tmp_path, [
        {"id": "live-plugin", "removed_at": "2026-09-01", "reason": "r"},
    ])
    with pytest.raises(ValueError, match="冲突"):
        _load_tombstones(tmp_path)


def test_non_conflicting_tombstone_passes(tmp_path: Path) -> None:
    (tmp_path / "templates" / "social--market--weibo-search").mkdir(parents=True)
    _write(tmp_path, [
        {"id": "social/market/other", "removed_at": "2026-09-01", "reason": "r"},
    ])
    rows = _load_tombstones(tmp_path)
    assert rows[0]["id"] == "social/market/other"


@pytest.mark.parametrize("bad_id", ["Demo/Plugin", "-demo", "social//market", "1demo"])
def test_tombstone_invalid_id_rejected(tmp_path: Path, bad_id: str) -> None:
    _write(tmp_path, [
        {"id": bad_id, "removed_at": "2026-09-01", "reason": "r"},
    ])
    with pytest.raises(ValueError, match="非法 ID"):
        _load_tombstones(tmp_path)
