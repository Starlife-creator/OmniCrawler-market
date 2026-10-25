"""P1-4：finalize_submission 可单测规则——SemVer 单调解析、overlay/载荷元数据提取、
category 固定回退、模板元数据提取。

归属锁 / 版本单调拒绝 / 禁止覆盖 / 审核哈希钉死等内联分支由 finalize 主流程守卫，
其依赖的比对原语已在 contract / rules / identity 测试中锁定；端到端 fixture 属后续
集成回归（见状态报告 P2-11/P2-10 配套说明）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import finalize_submission as finalize


# --- SemVer 单调键 -------------------------------------------------------------
def test_semver_key_parses_release_version() -> None:
    assert finalize._semver_key("1.2.3")[:3] == (1, 2, 3)


@pytest.mark.parametrize("bad", ["1.2", "1.2.3.4", "latest", "v1.2.3", ""])
def test_semver_key_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError, match="SemVer"):
        finalize._semver_key(bad)


def test_release_sorts_after_prerelease() -> None:
    assert finalize._semver_key("1.0.0") > finalize._semver_key("1.0.0-rc1")


def test_numeric_prerelease_orders_before_nonnumeric() -> None:
    assert finalize._semver_key("1.0.0-10") < finalize._semver_key("1.0.0-alpha")


def test_version_monotonic_increase_ordering() -> None:
    assert finalize._semver_key("1.0.0") > finalize._semver_key("0.9.9")
    assert finalize._semver_key("1.0.0") == finalize._semver_key("1.0.0")


# --- 插件元数据提取 -------------------------------------------------------------
def _write_plugin(source: Path, metadata: dict) -> None:
    lines = ["PLUGIN_METADATA = " + repr(metadata)]
    (source / "plugin.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _plugin_manifest() -> dict:
    return {"package_type": "plugin", "package_id": "demo", "version": "1.0.0"}


def test_metadata_extracts_payload_decl_and_overlay_fields(tmp_path: Path) -> None:
    metadata = {
        "name": "Demo",
        "version": "1.0.0",
        "permissions": ["records:read"],
        "domains": ["api.example.com"],
        "input_files": ["data/in.csv"],
        "dependencies": [{"name": "yaml", "version": "6.0", "license": "Apache-2.0"}],
        "required_capabilities": {"records.read": "1"},
        "license": "MIT",
        "description": "采集处理器",
        "plugin_types": ["processor"],
    }
    _write_plugin(tmp_path, metadata)
    overlay, payload = finalize._metadata(tmp_path, _plugin_manifest(), {})
    assert payload["permissions"] == ["records:read"]
    assert payload["dependencies"] == metadata["dependencies"]
    assert overlay["summary"] == "采集处理器"
    assert overlay["license"] == "MIT"
    assert overlay["plugin_types"] == ["processor"]


def test_category_falls_back_to_utility_not_plugin_type(tmp_path: Path) -> None:
    _write_plugin(tmp_path, {"name": "Demo", "version": "1.0.0",
                             "permissions": [], "license": "MIT",
                             "plugin_types": ["processor"]})
    overlay, _ = finalize._metadata(tmp_path, _plugin_manifest(), {})
    assert overlay["category"] == "utility"


def test_market_metadata_category_overrides_fallback(tmp_path: Path) -> None:
    _write_plugin(tmp_path, {"name": "Demo", "version": "1.0.0",
                             "permissions": [], "license": "MIT"})
    submission = {"market_metadata": {"category": "connector"}}
    overlay, _ = finalize._metadata(tmp_path, _plugin_manifest(), submission)
    assert overlay["category"] == "connector"


def test_literal_metadata_missing_returns_empty_dict(tmp_path: Path) -> None:
    (tmp_path / "plugin.py").write_text("x = 1\n", encoding="utf-8")
    assert finalize._literal_metadata(tmp_path / "plugin.py") == {}


# --- 模板元数据提取 --------------------------------------------------------------
def test_template_metadata_extracted_from_block(tmp_path: Path) -> None:
    (tmp_path / "template.yaml").write_text(
        yaml.safe_dump({
            "project": "demo",
            "source": {"seeds": ["https://example.com"]},
            "template": {
                "name": "Demo Template",
                "version": "1.0.0",
                "category": "general",
                "description": "模板描述",
                "min_core_version": "0.11.2",
                "license": "CC0-1.0",
            },
        }),
        encoding="utf-8",
    )
    manifest = {"package_type": "template", "package_id": "demo/tpl", "version": "1.0.0"}
    overlay, payload = finalize._metadata(tmp_path, manifest, {})
    assert overlay["name"] == "Demo Template"
    assert overlay["summary"] == "模板描述"
    assert overlay["compatible_core"] == ">=0.11.2"
    assert payload == {}
