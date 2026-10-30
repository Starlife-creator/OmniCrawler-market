"""P2-10 overlay↔载荷漂移比对、P3-10 运行文件分类、P2-6 依赖指纹负样例。"""
from __future__ import annotations

import pytest

from catalog_lib.contract import (
    classify_files,
    compare_overlay_payload,
    dependency_fingerprint,
    is_runtime_file,
    security_field_expansion,
)
from validate_submission import is_runtime_file as _validator_runtime, non_runtime_files

# P3-10：投稿器自包含镜像规则必须与共享分类模块逐文件一致（策略锁对齐）。
_CLASSIFICATION_CORPUS = [
    "plugin.py",
    "handlers/processor.py",
    "config/rules.yaml",
    "listing.md",
    "tests/test_plugin.py",
    "docs/guide.md",
    "examples/sample.py",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "docs/notes.txt",
    "handlers/a.rst",
]


def test_validator_mirror_agrees_with_library_classification() -> None:
    for rel in _CLASSIFICATION_CORPUS:
        assert _validator_runtime(rel) == is_runtime_file(rel), rel
    runtime, non_runtime = classify_files(_CLASSIFICATION_CORPUS)
    assert sorted(non_runtime) == sorted(
        non_runtime_files({rel: None for rel in _CLASSIFICATION_CORPUS})
    )
    assert sorted(runtime) == sorted(
        rel for rel in _CLASSIFICATION_CORPUS if is_runtime_file(rel)
    )


# --- P2-10 overlay ↔ payload 一致 ------------------------------------------
def test_identical_declarations_have_no_drift() -> None:
    overlay = {
        "permissions": ["records:read", "network:scoped"],
        "domains": ["api.example.com"],
        "input_files": ["data/in.csv"],
        "dependencies": [{"name": "httpx", "version": "0.27.0", "license": "MIT"}],
        "required_capabilities": {"network.fetch": "1"},
    }
    assert compare_overlay_payload(overlay, overlay) == []


def test_permission_expansion_in_overlay_flagged() -> None:
    payload = {"permissions": ["records:read"]}
    overlay = {"permissions": ["records:read", "secrets:read"]}
    drift = compare_overlay_payload(overlay, payload)
    assert any("permissions" in issue and "secrets:read" in issue for issue in drift)


def test_payload_only_dependency_flagged_as_drift() -> None:
    overlay = {"dependencies": []}
    payload = {"dependencies": [{"name": "openpyxl"}]}
    drift = compare_overlay_payload(overlay, payload)
    assert any("openpyxl" in issue for issue in drift)


def test_domain_casefold_normalization() -> None:
    overlay = {"domains": ["API.Example.com"]}
    payload = {"domains": ["api.example.com"]}
    assert compare_overlay_payload(overlay, payload) == []


# --- P2-10 门 4 扩权检测 ----------------------------------------------------
def test_security_expansion_detects_new_permission() -> None:
    prev = {"permissions": ["records:read"]}
    new = {"permissions": ["records:read", "network:scoped"]}
    expansions = security_field_expansion(prev, new)
    assert any("permissions" in item for item in expansions)


def test_security_expansion_detects_dependency_added() -> None:
    prev = {"dependencies": []}
    new = {"dependencies": [{"name": "httpx"}]}
    expansions = security_field_expansion(prev, new)
    assert any("dependencies" in item for item in expansions)


def test_security_expansion_empty_when_identical() -> None:
    entry = {"permissions": ["records:read"], "domains": ["a.com"], "dependencies": []}
    assert security_field_expansion(entry, entry) == []


# --- P3-10 运行必需文件分类 ---------------------------------------------------
@pytest.mark.parametrize(
    "runtime",
    ["plugin.py", "config/a.yaml", "listing.md", "handlers/download.py"],
)
def test_runtime_files_classified(runtime: str) -> None:
    assert is_runtime_file(runtime) is True


@pytest.mark.parametrize(
    "non_runtime",
    [
        "tests/test_x.py",
        "docs/guide.md",
        "examples/demo.py",
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "docs/notes.txt",
    ],
)
def test_non_runtime_files_classified(non_runtime: str) -> None:
    assert is_runtime_file(non_runtime) is False


def test_classify_files_splits_into_two_groups() -> None:
    runtime, non_runtime = classify_files(
        ["plugin.py", "tests/test_x.py", "README.md", "handlers/a.py"]
    )
    assert runtime == ["plugin.py", "handlers/a.py"]
    assert non_runtime == ["tests/test_x.py", "README.md"]


# --- P2-6 依赖规范化指纹 -------------------------------------------------------
def test_dependency_fingerprint_order_independent() -> None:
    left = dependency_fingerprint(
        [{"name": "httpx", "version": "0.27.0", "license": "MIT"},
         {"name": "yaml", "version": "6.0", "license": "Apache-2.0"}]
    )
    right = dependency_fingerprint(
        [{"name": "yaml", "version": "6.0", "license": "Apache-2.0"},
         {"name": "httpx", "version": "0.27.0", "license": "MIT"}]
    )
    assert left == right


def test_dependency_fingerprint_changes_with_name() -> None:
    base = [{"name": "httpx", "version": "0.27.0", "license": "MIT"}]
    changed = [{"name": "aiohttp", "version": "3.10", "license": "Apache-2.0"}]
    assert dependency_fingerprint(base) != dependency_fingerprint(changed)
