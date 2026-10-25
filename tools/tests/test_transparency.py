"""P3-11：透明日志 POSIX 路径归一、历史迁移与 CI 校验负样例。"""
from __future__ import annotations

import json
from pathlib import Path

from catalog_lib.transparency import (
    canonicalize_entry,
    check_transparency_log,
    migrate_transparency_log,
)


def test_canonicalize_entry_converts_backslashes_to_posix() -> None:
    entry = {
        "operation": "sign",
        "plugin": "plugins\\example_news\\plugin.py",
        "package_manifest_file": "plugins\\x\\package.manifest.json",
        "note": "保留非路径字段",
    }
    out = canonicalize_entry(entry)
    assert out["plugin"] == "plugins/example_news/plugin.py"
    assert out["package_manifest_file"] == "plugins/x/package.manifest.json"
    assert out["note"] == "保留非路径字段"


def test_migrate_transparency_log_normalizes_history(tmp_path: Path) -> None:
    log = tmp_path / "signing_transparency.jsonl"
    log.write_text(
        "\n".join([
            json.dumps({"operation": "sign", "plugin": "plugins\\a\\plugin.py"}, sort_keys=True),
            json.dumps({"operation": "finalize-package", "package_id": "b"}, sort_keys=True),
        ]) + "\n",
        encoding="utf-8",
    )
    changed = migrate_transparency_log(log)
    assert changed == 1
    lines = log.read_text(encoding="utf-8").splitlines()
    assert "plugins/a/plugin.py" in lines[0]
    assert "\\" not in lines[0]


def test_check_transparency_log_detects_backslash(tmp_path: Path) -> None:
    log = tmp_path / "signing_transparency.jsonl"
    log.write_text(
        json.dumps({"operation": "sign", "plugin": "plugins\\a\\plugin.py"}) + "\n",
        encoding="utf-8",
    )
    findings = check_transparency_log(log)
    assert findings and "反斜杠" in findings[0]


def test_check_transparency_log_detects_invalid_json(tmp_path: Path) -> None:
    log = tmp_path / "signing_transparency.jsonl"
    log.write_text("{not json}\n", encoding="utf-8")
    findings = check_transparency_log(log)
    assert findings and "JSON 非法" in findings[0]


def test_check_transparency_log_clean_when_missing(tmp_path: Path) -> None:
    assert check_transparency_log(tmp_path / "missing.jsonl") == []
