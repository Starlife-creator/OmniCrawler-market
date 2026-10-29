"""P1-4：scan_market 目录形态负样例——符号链接拒绝、versions 保留路径占用拒绝、
版本目录名与 manifest 版本一致性、空 versions 容器拒绝、非目录条目拒绝。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scan_market import scan_market


def _registry(tmp_path: Path) -> Path:
    (tmp_path / "plugins").mkdir()
    (tmp_path / "templates").mkdir()
    return tmp_path


def _manifest(version: str, files: dict[str, str]) -> dict:
    return {"schema_version": 1, "version": version, "files": files}


def _legacy_package(root: Path, *, version: str = "1.0.0", files_extra: dict | None = None) -> None:
    plugin = root / "plugin.py"
    plugin.write_text("# legacy processor\n", encoding="utf-8")
    digest = __import__("hashlib").sha256(plugin.read_bytes()).hexdigest()
    files = {"plugin.py": f"sha256:{digest}"}
    if files_extra:
        files.update(files_extra)
    (root / "package.manifest.json").write_text(
        json.dumps(_manifest(version, files), sort_keys=True), encoding="utf-8"
    )


def test_clean_legacy_package_scans_without_errors(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    root = registry / "plugins" / "demo"
    root.mkdir()
    _legacy_package(root)
    assert scan_market(registry) == 0


def test_symlink_registry_path_rejected(tmp_path: Path, require_symlink: None) -> None:
    registry = _registry(tmp_path)
    target = registry / "plugins" / "real"
    target.mkdir()
    (registry / "plugins" / "link").symlink_to(target)
    with pytest.raises(ValueError, match="Linked registry path"):
        scan_market(registry)


def test_legacy_payload_owning_versions_path_rejected(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    root = registry / "plugins" / "demo"
    root.mkdir()
    versions = root / "versions" / "1.0.0"
    versions.mkdir(parents=True)
    (versions / "plugin.py").write_text("# versioned\n", encoding="utf-8")
    (versions / "package.manifest.json").write_text(
        json.dumps(_manifest("1.0.0", {"plugin.py": "sha256:x"}), sort_keys=True),
        encoding="utf-8",
    )
    _legacy_package(root, files_extra={"versions/1.0.0/plugin.py": "sha256:x"})
    with pytest.raises(ValueError, match="reserved versions path"):
        scan_market(registry)


def test_version_directory_name_mismatches_manifest_version_rejected(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    root = registry / "plugins" / "demo"
    root.mkdir()
    version_pkg = root / "versions" / "1.0.0"
    version_pkg.mkdir(parents=True)
    (version_pkg / "plugin.py").write_text("# versioned\n", encoding="utf-8")
    (version_pkg / "package.manifest.json").write_text(
        json.dumps(_manifest("2.0.0", {"plugin.py": "sha256:x"}), sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Version directory mismatch"):
        scan_market(registry)


def test_empty_versions_container_rejected(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    root = registry / "plugins" / "demo"
    (root / "versions").mkdir(parents=True)
    with pytest.raises(ValueError, match="Empty versions container"):
        scan_market(registry)


def test_unexpected_non_directory_entry_rejected(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    (registry / "plugins" / "stray.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected registry entry"):
        scan_market(registry)
