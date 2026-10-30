"""P2-8：市场仓自包含身份模型与签名原语回归；确认工具链不再注入主仓 sys.path。"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from catalog_lib.identity import (
    CreatorIdentity,
    FingerprintMismatchError,
    IdentityError,
    derive_fingerprint,
)
from catalog_lib.signing import sign_bytes, sign_file, verify_plugin

REGISTRY = Path(__file__).resolve().parents[2]
TOOLS = REGISTRY / "tools"


def _keypair() -> tuple[Ed25519PrivateKey, bytes, bytes]:
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes_raw()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, public_raw, public_pem


# --- CreatorIdentity ---------------------------------------------------------
def test_identity_roundtrip_fingerprint_derived_from_public_key() -> None:
    _, public_raw, _ = _keypair()
    identity = CreatorIdentity(username="alice", public_key=public_raw)
    restored = CreatorIdentity.from_dict(identity.to_dict())
    assert restored.username == "alice"
    assert restored.public_key == public_raw
    assert restored.key_fingerprint == derive_fingerprint(public_raw)


def test_identity_self_declared_fingerprint_mismatch_rejected() -> None:
    _, public_raw, _ = _keypair()
    payload = {
        "username": "alice",
        "public_key": base64.b64encode(public_raw).decode("ascii"),
        "key_fingerprint": "0" * 32,
    }
    with pytest.raises(FingerprintMismatchError, match="指纹与公钥不符"):
        CreatorIdentity.from_dict(payload)


def test_identity_bad_base64_rejected() -> None:
    payload = {"username": "alice", "public_key": "not-base64!!"}
    with pytest.raises(IdentityError):
        CreatorIdentity.from_dict(payload)


def test_identity_empty_public_key_rejected() -> None:
    with pytest.raises(IdentityError):
        CreatorIdentity(username="alice", public_key=b"")


# --- 签名原语 -----------------------------------------------------------------
def test_sign_and_verify_roundtrip(tmp_path: Path) -> None:
    private, _, public_pem = _keypair()
    data = b"catalog body"
    signature = sign_bytes(data, private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    target = tmp_path / "catalog.json"
    target.write_bytes(data)
    sig_path = sign_file(target, private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    assert sig_path.is_file()
    ok, reason = verify_plugin(str(target), public_pem.decode("ascii"))
    assert ok, reason


def test_verify_plugin_rejects_tampered_payload(tmp_path: Path) -> None:
    private, _, public_pem = _keypair()
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    target = tmp_path / "plugin.py"
    target.write_bytes(b"original")
    sign_file(target, pem)
    target.write_bytes(b"tampered")
    ok, reason = verify_plugin(str(target), public_pem.decode("ascii"))
    assert not ok and "篡改" in reason


def test_verify_plugin_rejects_missing_signature(tmp_path: Path) -> None:
    _, _, public_pem = _keypair()
    target = tmp_path / "plugin.py"
    target.write_bytes(b"body")
    ok, reason = verify_plugin(str(target), public_pem.decode("ascii"))
    assert not ok and "签名文件" in reason


def test_verify_plugin_rejects_wrong_trust_root(tmp_path: Path) -> None:
    private, _, _ = _keypair()
    wrong_public = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    target = tmp_path / "plugin.py"
    target.write_bytes(b"body")
    sign_file(target, pem)
    ok, _ = verify_plugin(str(target), wrong_public.decode("ascii"))
    assert not ok


# --- 解耦断言：工具源码不得再引用主仓 sys.path 注入 -----------------------------
@pytest.mark.parametrize("script", ["finalize_submission.py", "sign_catalog.py"])
def test_tools_do_not_import_main_repo(script: str) -> None:
    source = (TOOLS / script).read_text(encoding="utf-8")
    assert "omnicrawler.plugins" not in source
    assert "MAIN_SRC" not in source
    assert "OmniCrawler/src" not in source
