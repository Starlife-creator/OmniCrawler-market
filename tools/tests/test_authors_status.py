"""P2-4：作者密钥状态/吊销/代际字段校验、吊销拒绝与多根过渡验签。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from catalog_lib.authors import _check_author, load_authors
from catalog_lib.signing import sign_bytes, verify_against_roots


def _write_author(registry: Path, record: dict) -> Path:
    authors = registry / "authors"
    authors.mkdir(parents=True, exist_ok=True)
    import yaml

    (authors / "alice.yaml").write_text(
        yaml.safe_dump(record, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return authors / "alice.yaml"


def test_active_author_passes_check(tmp_path: Path) -> None:
    _write_author(tmp_path, {
        "market_handle": "alice", "username": "alice",
        "fingerprint": "f" * 32, "roles": ["publisher"], "status": "active",
    })
    authors = load_authors(tmp_path)
    _check_author({"author_fingerprint": "f" * 32, "publisher": "alice", "id": "p"}, authors)


def test_revoked_author_record_rejected(tmp_path: Path) -> None:
    _write_author(tmp_path, {
        "market_handle": "alice", "username": "alice",
        "fingerprint": "f" * 32, "roles": ["publisher"],
        "status": "revoked", "revoked_at": "2026-10-01",
    })
    authors = load_authors(tmp_path)
    with pytest.raises(ValueError, match="密钥已吊销"):
        _check_author({"author_fingerprint": "f" * 32, "publisher": "alice", "id": "p"}, authors)


@pytest.mark.parametrize("record", [
    {"status": "banned"},
    {"status": "revoked"},
    {"status": "active", "revoked_at": "2026-10-01"},
    {"status": "revoked", "revoked_at": "not-a-date"},
    {"key_generation": -1},
    {"key_generation": "three"},
    {"key_id": "  "},
])
def test_author_lifecycle_fields_validated(tmp_path: Path, record: dict) -> None:
    base = {"market_handle": "alice", "username": "alice",
            "fingerprint": "f" * 32, "roles": ["publisher"]}
    base.update(record)
    _write_author(tmp_path, base)
    with pytest.raises(ValueError):
        load_authors(tmp_path)


def test_multi_root_accepts_second_generation_signature(tmp_path: Path) -> None:
    root1 = Ed25519PrivateKey.generate()
    root2 = Ed25519PrivateKey.generate()
    keys = tmp_path / "keys"
    keys.mkdir(exist_ok=True)
    (keys / "plugin_trust.pub.pem").write_bytes(
        root1.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    (keys / "plugin_trust.g2.pub.pem").write_bytes(
        root2.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    data = b"catalog body"
    sig_root2 = sign_bytes(
        data,
        root2.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    ok, accepted = verify_against_roots(tmp_path, data, sig_root2)
    assert ok and "g2" in accepted
    sig_root1 = sign_bytes(
        data,
        root1.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    ok, accepted = verify_against_roots(tmp_path, data, sig_root1)
    assert ok and "plugin_trust.pub.pem" in accepted


def test_explicit_trust_source_not_falling_back(tmp_path: Path) -> None:
    root1 = Ed25519PrivateKey.generate()
    root2 = Ed25519PrivateKey.generate()
    keys = tmp_path / "keys"
    keys.mkdir(exist_ok=True)
    (keys / "plugin_trust.pub.pem").write_bytes(
        root1.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    data = b"catalog body"
    sig_root2 = sign_bytes(
        data,
        root2.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    # 显式指定 root1 公钥文本时不得回退目录根（fail-closed）。
    ok, _ = verify_against_roots(
        tmp_path, data, sig_root2,
        trust_source=root1.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode(),
    )
    assert not ok
