"""市场仓工具链回归（P1-4）：schema 契约、路径安全、墓碑模型负样例。

覆盖本轮落地：P0-2 条目级吊销结构校验、P2-2 source_base 白名单、P2-3 能力名
宿主白名单、P3-4 路径分隔符/绝对路径/当前目录段拒绝、P0-2 版本级墓碑。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalog_lib.common import ALLOWED_CAPABILITIES, _require_contained
from catalog_lib.schema import _entry_from_yaml
from catalog_lib.tombstones import _load_tombstones


def _baseline() -> dict:
    return {
        "id": "demo-processor",
        "name": "Demo",
        "version": "1.0.0",
        "publisher": "starlife",
        "category": "source",
        "summary": "demo",
        "description_file": "plugins/demo/listing.md",
        "plugin_file": "plugins/demo/plugin.py",
        "signature_file": "plugins/demo/plugin.py.sig",
        "signature_algorithm": "ed25519",
        "permissions": ["records:read"],
        "compatible_core": ">=1.0.0",
        "license": "MIT",
        "plugin_types": ["processor"],
    }


# --- schema：合法条目 -------------------------------------------------------
def test_baseline_entry_passes() -> None:
    entry = _entry_from_yaml(_baseline(), Path("plugins/demo/plugin.yaml"))
    assert entry["id"] == "demo-processor"


def test_revocation_and_source_base_and_known_capabilities_pass() -> None:
    manifest = _baseline()
    manifest.update({
        "revoked": "恶意代码",
        "deprecated": {"reason": "迁移到 demo-processor-2"},
        "revoked_versions": ["1.0.0"],
        "source_base": "https://raw.example.com/owner/repo/main/",
        "required_capabilities": {"records.read": ">=1", "network.fetch": "1"},
    })
    entry = _entry_from_yaml(manifest, Path("plugins/demo/plugin.yaml"))
    assert entry["source_base"] == "https://raw.example.com/owner/repo/main"


# --- schema：负样例 ---------------------------------------------------------
def test_unknown_capability_rejected() -> None:
    manifest = _baseline()
    manifest["required_capabilities"] = {"future.magic": ">=1"}
    with pytest.raises(ValueError, match="宿主不支持的能力|required_capabilities"):
        _entry_from_yaml(manifest, Path("plugin.yaml"))


def test_capability_whitelist_covers_declared() -> None:
    # 白名单非空且与主仓键集合对齐（名称存在性由本集合保证）。
    assert "records.read" in ALLOWED_CAPABILITIES
    assert "network.fetch" in ALLOWED_CAPABILITIES


@pytest.mark.parametrize("bad_url", [
    "ftp://example.com/a",
    "example.com/path",
    "/abs/path",
    "https://example.com/ path",
])
def test_source_base_must_be_http_s_origin(bad_url: str) -> None:
    manifest = _baseline()
    manifest["source_base"] = bad_url
    with pytest.raises(ValueError, match="source_base"):
        _entry_from_yaml(manifest, Path("plugin.yaml"))


def test_revocation_field_structure_validated() -> None:
    manifest = _baseline()
    manifest["revoked"] = 123  # 须为非空字符串或映射
    with pytest.raises(ValueError, match="revoked"):
        _entry_from_yaml(manifest, Path("plugin.yaml"))

    manifest2 = _baseline()
    manifest2["revoked_versions"] = "1.0.0"  # 须为列表
    with pytest.raises(ValueError, match="revoked_versions"):
        _entry_from_yaml(manifest2, Path("plugin.yaml"))

    manifest3 = _baseline()
    manifest3["deprecated"] = True  # 须为非空字符串或映射
    with pytest.raises(ValueError, match="deprecated"):
        _entry_from_yaml(manifest3, Path("plugin.yaml"))


def test_unknown_field_still_rejected() -> None:
    manifest = _baseline()
    manifest["not_a_real_field"] = 1
    with pytest.raises(ValueError, match="未知字段"):
        _entry_from_yaml(manifest, Path("plugin.yaml"))


# --- 路径包含性（P3-4）-----------------------------------------------------
def test_require_contained_accepts_plain_relative(tmp_path: Path) -> None:
    resolved = _require_contained(tmp_path, tmp_path, "plugins/demo/plugin.py", "测试")
    assert resolved.is_relative_to(tmp_path.resolve())


def test_require_contained_rejects_absolute(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="绝对路径"):
        _require_contained(tmp_path, tmp_path, "/etc/passwd", "测试")


def test_require_contained_rejects_backslash(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="反斜杠"):
        _require_contained(tmp_path, tmp_path, "plugins\\demo\\x.py", "测试")


def test_require_contained_rejects_current_dir_segment(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="当前目录段"):
        _require_contained(tmp_path, tmp_path, "./plugins/demo/x.py", "测试")


def test_require_contained_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="逃出 registry"):
        _require_contained(tmp_path, tmp_path, "plugins/../../etc/x", "测试")


# --- 墓碑模型（P0-2 配套）--------------------------------------------------
def _write_tombstones(registry: Path, rows: list[dict]) -> None:
    (registry / "tombstones.json").write_text(
        json.dumps(rows), encoding="utf-8"
    )


def test_tombstone_full_entry_and_version_scoped_pass(tmp_path: Path) -> None:
    _write_tombstones(tmp_path, [
        {"id": "dead-plugin", "removed_at": "2026-09-01", "reason": "恶意吊销"},
        {"id": "pinned-version", "removed_at": "2026-09-02", "reason": "版本被撤",
         "version": "1.0.0"},
    ])
    rows = _load_tombstones(tmp_path)
    assert rows[0]["id"] == "dead-plugin"
    assert rows[1]["version"] == "1.0.0"


def test_tombstone_missing_required_field_rejected(tmp_path: Path) -> None:
    _write_tombstones(tmp_path, [{"id": "x", "removed_at": "2026-09-01"}])  # 缺 reason
    with pytest.raises(ValueError, match="必填字段 reason"):
        _load_tombstones(tmp_path)


def test_tombstone_version_type_rejected(tmp_path: Path) -> None:
    _write_tombstones(tmp_path, [
        {"id": "x", "removed_at": "2026-09-01", "reason": "r", "version": 5},
    ])
    with pytest.raises(ValueError, match="version"):
        _load_tombstones(tmp_path)


def test_tombstone_conflicts_with_live_directory(tmp_path: Path) -> None:
    (tmp_path / "plugins" / "live-plugin").mkdir(parents=True)
    _write_tombstones(tmp_path, [
        {"id": "live-plugin", "removed_at": "2026-09-01", "reason": "r"},
    ])
    with pytest.raises(ValueError, match="冲突"):
        _load_tombstones(tmp_path)
