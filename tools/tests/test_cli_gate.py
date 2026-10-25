"""P1-4：cli 门禁入口 fail-closed 与持久序列号读取负样例。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalog_lib.cli import _existing_catalog_sequence, check, main, publish_check


def test_sequence_missing_catalog_returns_none(tmp_path: Path) -> None:
    assert _existing_catalog_sequence(tmp_path) is None


def test_sequence_reads_positive_int(tmp_path: Path) -> None:
    (tmp_path / "catalog.json").write_text(
        json.dumps({"sequence": 7}), encoding="utf-8"
    )
    assert _existing_catalog_sequence(tmp_path) == 7


@pytest.mark.parametrize("value", [0, -3, "five", None])
def test_sequence_invalid_values_return_none(tmp_path: Path, value: object) -> None:
    (tmp_path / "catalog.json").write_text(
        json.dumps({"sequence": value}), encoding="utf-8"
    )
    assert _existing_catalog_sequence(tmp_path) is None


def test_sequence_invalid_json_returns_none(tmp_path: Path) -> None:
    (tmp_path / "catalog.json").write_text("{not json", encoding="utf-8")
    assert _existing_catalog_sequence(tmp_path) is None


def test_check_rejects_registry_without_plugins_dir(tmp_path: Path) -> None:
    assert check(tmp_path) == 1


def test_publish_check_rejects_empty_registry(tmp_path: Path) -> None:
    assert publish_check(tmp_path) == 1


def test_main_rejects_nonexistent_registry_directory(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert main(["--registry", str(missing), "--check"]) == 1


def test_main_publish_check_on_empty_registry_fails_closed(tmp_path: Path) -> None:
    assert main(["--registry", str(tmp_path), "--publish-check"]) == 1
