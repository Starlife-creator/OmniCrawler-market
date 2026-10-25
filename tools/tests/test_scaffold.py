"""P2-9：脚手架对齐 schema、产物先过门1/门3 自检；非法输入落盘前回滚。"""
from __future__ import annotations

from pathlib import Path

import pytest

import new_submission


def test_plugin_scaffold_generated_and_self_checked(tmp_path: Path) -> None:
    out = tmp_path / "plugin"
    code = new_submission.main([
        "plugin", "demo-fetcher", "演示采集器", "1.0.0",
        "--summary", "演示最小骨架", "--out", str(out),
    ])
    assert code == 0
    assert (out / "plugin.py").is_file()
    assert (out / "plugin.yaml").is_file()
    assert (out / "listing.md").is_file()
    assert (out / "tests" / "test_contract.py").is_file()


def test_template_scaffold_generated_and_self_checked(tmp_path: Path) -> None:
    out = tmp_path / "template"
    code = new_submission.main([
        "template", "social/market/demo", "演示模板", "1.0.0",
        "--summary", "演示模板骨架", "--out", str(out),
    ])
    assert code == 0
    assert (out / "template.yaml").is_file()
    assert (out / "listing.md").is_file()


def test_scaffold_rejects_existing_directory(tmp_path: Path) -> None:
    out = tmp_path / "plugin"
    out.mkdir()
    code = new_submission.main([
        "plugin", "demo-fetcher", "演示采集器", "1.0.0",
        "--summary", "x", "--out", str(out),
    ])
    assert code == 2


@pytest.mark.parametrize("bad_id", ["Demo", "social//market", "1demo"])
def test_scaffold_rejects_invalid_id(tmp_path: Path, bad_id: str) -> None:
    code = new_submission.main([
        "plugin", bad_id, "演示", "1.0.0", "--summary", "x", "--out", str(tmp_path / "x"),
    ])
    assert code == 2


def test_scaffold_rejects_missing_summary(tmp_path: Path) -> None:
    code = new_submission.main([
        "plugin", "demo-fetcher", "演示", "1.0.0", "--out", str(tmp_path / "x"),
    ])
    assert code == 2


def test_scaffold_rejects_non_semver_version(tmp_path: Path) -> None:
    code = new_submission.main([
        "plugin", "demo-fetcher", "演示", "latest",
        "--summary", "x", "--out", str(tmp_path / "x"),
    ])
    assert code == 2


def test_self_check_plugin_rejects_name_mismatch(tmp_path: Path) -> None:
    out = tmp_path / "p"
    out.mkdir()
    metadata = {"name": "A", "version": "1.0.0", "license": "MIT",
                "plugin_types": ["source"], "permissions": [], "domains": [],
                "input_files": [], "dependencies": [], "required_capabilities": {},
                "execution_mode": "subprocess", "compatible_core": ">=0.11.2"}
    yaml_meta = {"name": "B", "version": "1.0.0", "license": "MIT",
                 "compatible_core": ">=0.11.2"}
    (out / "plugin.py").write_text(
        "PLUGIN_METADATA = {'name': 'A', 'version': '1.0.0', 'license': 'MIT',\n"
        " 'plugin_types': ['source'], 'permissions': [], 'domains': [],\n"
        " 'input_files': [], 'dependencies': [], 'required_capabilities': {},\n"
        " 'execution_mode': 'subprocess', 'compatible_core': '>=0.11.2'}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="name"):
        new_submission._self_check_plugin(out, "demo", metadata, yaml_meta)


def test_self_check_template_rejects_missing_required_field(tmp_path: Path) -> None:
    block = {"id": "social/market/x", "name": "x", "version": "1.0.0",
             "category": "general", "compatible_core": ">=0.11.2"}
    with pytest.raises(ValueError, match="license"):
        new_submission._self_check_template(tmp_path, "social/market/x", block)
