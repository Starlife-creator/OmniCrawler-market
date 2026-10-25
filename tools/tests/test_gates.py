"""P1-1 门 1 / 门 3 下沉投稿校验器的负样例回归。

覆盖主仓 plugin_audit 同套规则在市场投稿侧的落地：
- 门 1：network⇒domains、files:read⇒input_files、subprocess 禁 import 宿主、
  subprocess 禁 ui:/hook、载荷许可白名单；
- 门 3：dependencies 必填、依赖许可白名单、semver 区间格式、声明↔实测导入图双向一致。
"""
from __future__ import annotations

from pathlib import Path

import pytest

import validate_submission as validator


def _meta(**overrides: object) -> dict:
    base: dict = {
        "name": "demo",
        "version": "1.0.0",
        "permissions": [],
        "domains": [],
        "input_files": [],
        "dependencies": [],
        "execution_mode": "subprocess",
        "plugin_types": ["source"],
    }
    base.update(overrides)
    return base


# --- 门 1：network ⇒ domains -------------------------------------------------
def test_gate1_network_without_domains_rejected(tmp_path: Path) -> None:
    meta = _meta(permissions=["network:scoped"], domains=[])
    with pytest.raises(ValueError, match="domains"):
        validator.gate1_declaration_consistency(tmp_path, meta, "")


def test_gate1_network_with_valid_domains_passes(tmp_path: Path) -> None:
    meta = _meta(permissions=["network:scoped"], domains=["api.github.com"])
    validator.gate1_declaration_consistency(tmp_path, meta, "")


def test_gate1_invalid_domain_shape_rejected(tmp_path: Path) -> None:
    for bad in ["API.GitHub.com", "example..com", "-bad.com"]:
        meta = _meta(permissions=["network:scoped"], domains=[bad])
        with pytest.raises(ValueError, match="domains"):
            validator.gate1_declaration_consistency(tmp_path, meta, "")


# --- 门 1：files:read ⇒ input_files ------------------------------------------
def test_gate1_files_read_without_input_files_rejected(tmp_path: Path) -> None:
    meta = _meta(permissions=["files:read"], input_files=[])
    with pytest.raises(ValueError, match="input_files"):
        validator.gate1_declaration_consistency(tmp_path, meta, "")


def test_gate1_input_files_traversal_rejected(tmp_path: Path) -> None:
    meta = _meta(permissions=["files:read"], input_files=["../etc/passwd"])
    with pytest.raises(ValueError, match="非法相对路径|input_files"):
        validator.gate1_declaration_consistency(tmp_path, meta, "")


def test_gate1_files_read_with_allowlist_passes(tmp_path: Path) -> None:
    meta = _meta(permissions=["files:read"], input_files=["*.xlsx"])
    validator.gate1_declaration_consistency(tmp_path, meta, "")


# --- 门 1：subprocess 隔离边界 ------------------------------------------------
def test_gate1_subprocess_imports_host_rejected(tmp_path: Path) -> None:
    source = "import omnicrawler.plugins.market_client\n"
    meta = _meta()
    with pytest.raises(ValueError, match="宿主核心"):
        validator.gate1_declaration_consistency(tmp_path, meta, source)


def test_gate1_subprocess_allowed_sdk_import_passes(tmp_path: Path) -> None:
    source = "import omnicrawler_sdk\nfrom omnicrawler_sdk import network\n"
    validator.gate1_declaration_consistency(tmp_path, _meta(), source)


def test_gate1_subprocess_forbidden_ui_permission_rejected(tmp_path: Path) -> None:
    meta = _meta(permissions=["ui:window"])
    with pytest.raises(ValueError, match="ui:|hook"):
        validator.gate1_declaration_consistency(tmp_path, meta, "")


def test_gate1_subprocess_forbidden_hook_permission_rejected(tmp_path: Path) -> None:
    meta = _meta(permissions=["hook:frob"])
    with pytest.raises(ValueError, match="ui:|hook"):
        validator.gate1_declaration_consistency(tmp_path, meta, "")


# --- 门 1：载荷许可白名单 ------------------------------------------------------
def test_gate1_payload_license_not_allowlisted_rejected(tmp_path: Path) -> None:
    meta = _meta(license="GPL-3.0-only")
    with pytest.raises(ValueError, match="license|白名单"):
        validator.gate1_declaration_consistency(tmp_path, meta, "")


def test_gate1_payload_license_allowlisted_passes(tmp_path: Path) -> None:
    validator.gate1_declaration_consistency(tmp_path, _meta(license="MIT"), "")


# --- 门 3：dependencies 必填 / 许可 / 区间格式 --------------------------------
def test_gate3_missing_dependencies_rejected(tmp_path: Path) -> None:
    meta = _meta()
    del meta["dependencies"]
    with pytest.raises(ValueError, match="dependencies 未声明"):
        validator.gate3_dependencies_consistency(tmp_path, meta, "")


def test_gate3_dependency_license_not_allowlisted_rejected(tmp_path: Path) -> None:
    meta = _meta(dependencies=[{"name": "httpx", "version": ">=0.27,<1.0", "license": "GPL-3.0-only"}])
    with pytest.raises(ValueError, match="许可.*不在 SPDX"):
        validator.gate3_dependencies_consistency(tmp_path, meta, "")


@pytest.mark.parametrize("bad_version", ["latest", ">=foo", "1.2.x", "^abc"])
def test_gate3_dependency_version_format_rejected(tmp_path: Path, bad_version: str) -> None:
    meta = _meta(dependencies=[{"name": "httpx", "version": bad_version, "license": "MIT"}])
    with pytest.raises(ValueError, match="版本约束格式非法"):
        validator.gate3_dependencies_consistency(tmp_path, meta, "")


@pytest.mark.parametrize("good_version", [">=0.27,<1.0", "==6.0.2", "^2.0.0", "1.2.3", "~1.2"])
def test_gate3_dependency_version_format_accepted(tmp_path: Path, good_version: str) -> None:
    (tmp_path / "plugin.py").write_text("import httpx\n", encoding="utf-8")
    meta = _meta(dependencies=[{"name": "httpx", "version": good_version, "license": "MIT"}])
    validator.gate3_dependencies_consistency(tmp_path, meta, "import httpx\n")


# --- 门 3：声明 ↔ 实测导入图双向 -----------------------------------------------
def test_gate3_declared_but_not_imported_rejected(tmp_path: Path) -> None:
    meta = _meta(dependencies=[{"name": "httpx", "version": ">=0.27,<1.0", "license": "MIT"}])
    with pytest.raises(ValueError, match="未在实测导入图"):
        validator.gate3_dependencies_consistency(tmp_path, meta, "")


def test_gate3_imported_but_not_declared_rejected(tmp_path: Path) -> None:
    source = "import httpx\n"
    meta = _meta(dependencies=[])
    with pytest.raises(ValueError, match="未在 dependencies 声明"):
        validator.gate3_dependencies_consistency(tmp_path, meta, source)


def test_gate3_stdlib_imports_not_required(tmp_path: Path) -> None:
    source = "import json\nimport urllib.parse\nfrom pathlib import Path\n"
    validator.gate3_dependencies_consistency(tmp_path, _meta(dependencies=[]), source)


def test_gate3_local_sibling_module_not_third_party(tmp_path: Path) -> None:
    (tmp_path / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    source = "import helper\n"
    validator.gate3_dependencies_consistency(tmp_path, _meta(dependencies=[]), source)


def test_gate3_roundtrip_consistent_passes(tmp_path: Path) -> None:
    source = "import httpx\n"
    meta = _meta(dependencies=[{"name": "httpx", "version": ">=0.27,<1.0", "license": "MIT"}])
    validator.gate3_dependencies_consistency(tmp_path, meta, source)
