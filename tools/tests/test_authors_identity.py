"""P1-4：作者归属规则负样例——同指纹多用户名、pubkey_ref 缺失、自称指纹不符、
publisher 与指纹归属不一致、重复 handle、缺少 handle。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from catalog_lib.authors import _check_author, load_authors


def _write(registry: Path, handle: str, record: dict) -> None:
    authors = registry / "authors"
    authors.mkdir(parents=True, exist_ok=True)
    (authors / f"{handle}.yaml").write_text(
        yaml.safe_dump(record, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def test_fingerprint_only_record_accepted(tmp_path: Path) -> None:
    _write(tmp_path, "alice", {
        "market_handle": "alice", "username": "alice",
        "fingerprint": "f" * 32, "roles": ["publisher"],
    })
    authors = load_authors(tmp_path)
    _check_author({"id": "p", "publisher": "alice", "author_fingerprint": "f" * 32}, authors)


def test_same_fingerprint_multiple_usernames_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "alice", {
        "market_handle": "alice", "username": "alice", "fingerprint": "f" * 32,
    })
    _write(tmp_path, "bob", {
        "market_handle": "bob", "username": "bob", "fingerprint": "f" * 32,
    })
    with pytest.raises(ValueError, match="多个 username"):
        load_authors(tmp_path)


def test_pubkey_ref_missing_file_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "alice", {
        "market_handle": "alice", "username": "alice",
        "pubkey_ref": "../keys/alice.pub.pem",
    })
    with pytest.raises(ValueError, match="pubkey_ref 不存在"):
        load_authors(tmp_path)


def test_claimed_fingerprint_mismatches_public_key_rejected(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate()
    pub_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    keys = tmp_path / "keys"
    keys.mkdir(exist_ok=True)
    (keys / "alice.pub.pem").write_bytes(pub_pem)
    _write(tmp_path, "alice", {
        "market_handle": "alice", "username": "alice",
        "pubkey_ref": "../keys/alice.pub.pem",
        "fingerprint": "0" * 32,
    })
    with pytest.raises(ValueError, match="实际指纹"):
        load_authors(tmp_path)


def test_publisher_not_matching_fingerprint_owner_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "alice", {
        "market_handle": "alice", "username": "alice", "fingerprint": "f" * 32,
    })
    authors = load_authors(tmp_path)
    with pytest.raises(ValueError, match="publisher 'mallory'"):
        _check_author(
            {"id": "p", "publisher": "mallory", "author_fingerprint": "f" * 32},
            authors,
        )


def test_author_fingerprint_missing_from_manifest_rejected(tmp_path: Path) -> None:
    authors = load_authors(tmp_path)
    with pytest.raises(ValueError, match="缺少 author_fingerprint"):
        _check_author({"id": "p", "publisher": "alice"}, authors)


def test_author_filename_must_equal_handle(tmp_path: Path) -> None:
    # 文件名 ≠ market_handle 即 fail-closed（防止一文件多 handle / 重名静默覆盖）。
    _write(tmp_path, "alice-other", {"market_handle": "alice", "username": "alice"})
    with pytest.raises(ValueError, match="文件名必须等于 market_handle"):
        load_authors(tmp_path)



