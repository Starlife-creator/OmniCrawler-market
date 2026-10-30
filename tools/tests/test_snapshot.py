"""P1-2：离线快照签名 fail-closed 校验与新鲜度比对负样例。"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from catalog_lib.signing import sign_bytes
from catalog_lib.snapshot import export_snapshot, is_snapshot_fresh, verify_snapshot


def _make_root(tmp_path: Path, *, generated_at: datetime) -> tuple[Path, Ed25519PrivateKey]:
    private = Ed25519PrivateKey.generate()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    (tmp_path / "keys").mkdir(parents=True, exist_ok=True)
    (tmp_path / "keys" / "plugin_trust.pub.pem").write_bytes(public_pem)
    catalog = {"schema_version": 1, "generated_at": generated_at.isoformat(),
               "sequence": 1, "plugins": [], "templates": []}
    catalog_bytes = (json.dumps(catalog, sort_keys=True, ensure_ascii=False) + "\n").encode()
    (tmp_path / "catalog.json").write_bytes(catalog_bytes)
    (tmp_path / "catalog.json.sig").write_bytes(
        sign_bytes(catalog_bytes, private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
    )
    return tmp_path, private


def test_valid_fresh_snapshot_passes(tmp_path: Path) -> None:
    root, _ = _make_root(tmp_path, generated_at=datetime.now(UTC))
    ok, findings = verify_snapshot(root)
    assert ok, findings


def test_missing_signature_is_fail_closed(tmp_path: Path) -> None:
    root, _ = _make_root(tmp_path, generated_at=datetime.now(UTC))
    (root / "catalog.json.sig").unlink()
    ok, findings = verify_snapshot(root)
    assert not ok
    assert any("catalog.json.sig" in item for item in findings)


def test_tampered_catalog_rejected(tmp_path: Path) -> None:
    root, _ = _make_root(tmp_path, generated_at=datetime.now(UTC))
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    catalog["sequence"] = 99
    (root / "catalog.json").write_text(
        json.dumps(catalog, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    ok, findings = verify_snapshot(root)
    assert not ok
    assert any("签名无效" in item or "未覆盖" in item for item in findings)


def test_stale_snapshot_warns_but_does_not_block_without_require_fresh(tmp_path: Path) -> None:
    root, _ = _make_root(tmp_path, generated_at=datetime(2020, 1, 1, tzinfo=UTC))
    ok, findings = verify_snapshot(root, max_age_hours=24 * 30)
    assert ok
    assert any("warning:" in item and "陈旧" in item for item in findings)


def test_stale_snapshot_blocks_when_require_fresh(tmp_path: Path) -> None:
    root, _ = _make_root(tmp_path, generated_at=datetime(2020, 1, 1, tzinfo=UTC))
    ok, findings = verify_snapshot(root, require_fresh=True, max_age_hours=24 * 30)
    assert not ok
    assert any("陈旧" in item and "拒绝使用" in item for item in findings)


def test_is_snapshot_fresh_threshold_boundary() -> None:
    fresh_catalog = {"generated_at": datetime.now(UTC).isoformat()}
    stale_catalog = {"generated_at": (datetime.now(UTC) - timedelta(days=60)).isoformat()}
    assert is_snapshot_fresh(fresh_catalog, max_age_hours=24 * 30)[0]
    assert not is_snapshot_fresh(stale_catalog, max_age_hours=24 * 30)[0]


def test_export_snapshot_copies_core_materials(tmp_path: Path) -> None:
    source, _ = _make_root(tmp_path / "source", generated_at=datetime.now(UTC))
    (source / "authors").mkdir()
    (source / "authors" / "alice.yaml").write_text("username: alice\n", encoding="utf-8")
    dest = tmp_path / "snapshot"
    export_snapshot(source, dest)
    assert (dest / "catalog.json").is_file()
    assert (dest / "catalog.json.sig").is_file()
    assert (dest / "authors" / "alice.yaml").is_file()
