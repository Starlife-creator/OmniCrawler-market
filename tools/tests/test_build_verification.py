"""P1-3 构建态校验对齐主仓 verify_package 的负样例回归。

覆盖：schema_version 区间、精确文件集合相等、符号链接拒绝、私钥/凭据黑名单、
指纹↔身份↔条目交叉核对、文件哈希格式与内容比对、创作者整包签名验签。
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from catalog_lib.signing import _canonical_manifest, _verify_package_manifest


def _make_package(
    tmp_path: Path,
    *,
    manifest_overrides: dict | None = None,
    payload: bytes = b"print('hello')\n",
    extra_files: dict[str, bytes] | None = None,
    symlink: tuple[str, str] | None = None,
    tamper_creator_sig: bool = False,
    bad_hash_format: bool = False,
    keep_identity_in_files: bool = True,
) -> dict[str, Path | dict]:
    pkg = tmp_path / "demo"
    pkg.mkdir(exist_ok=True)
    creator_priv = Ed25519PrivateKey.generate()
    maintainer_priv = Ed25519PrivateKey.generate()
    creator_pub_raw = creator_priv.public_key().public_bytes_raw()
    fp = hashlib.sha256(creator_pub_raw).hexdigest()[:32]

    plugin = pkg / "plugin.py"
    if symlink is None:
        plugin.write_bytes(payload)
    file_digest = hashlib.sha256(payload).hexdigest()

    identity = {
        "username": "alice",
        "public_key": base64.b64encode(creator_pub_raw).decode("ascii"),
        "key_fingerprint": fp,
        "fingerprint_algorithm": "sha256",
    }
    identity_bytes = (json.dumps(identity, sort_keys=True) + "\n").encode("utf-8")
    identity_path = pkg / "creator.identity"
    identity_path.write_bytes(identity_bytes)
    identity_digest = hashlib.sha256(identity_bytes).hexdigest()

    manifest: dict = {
        "schema_version": 1,
        "package_id": "demo",
        "requested_username": "alice",
        "creator_fingerprint": fp,
        "files": {
            "plugin.py": f"sha256:{file_digest}",
            "creator.identity": f"sha256:{identity_digest}",
        },
        "plugin_file": "plugin.py",
        "signature_algorithm": "ed25519",
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    if keep_identity_in_files:
        manifest["files"].setdefault(
            "creator.identity", f"sha256:{identity_digest}"
        )
    if bad_hash_format:
        manifest["files"]["plugin.py"] = f"md5:{file_digest}"

    for name, content in (extra_files or {}).items():
        (pkg / name).parent.mkdir(parents=True, exist_ok=True)
        (pkg / name).write_bytes(content)
    if symlink:
        target, link = symlink
        (pkg / target).write_bytes(b"shadow\n")
        (pkg / link).symlink_to(target)

    manifest_path = pkg / "package.manifest.json"
    data = _canonical_manifest(manifest)
    manifest_path.write_bytes(data)
    creator_sig = pkg / "package.manifest.creator.sig"
    creator_sig.write_bytes(
        b"\x00" * 64 if tamper_creator_sig else creator_priv.sign(data)
    )
    maintainer_sig = pkg / "package.manifest.maintainer.sig"
    maintainer_sig.write_bytes(maintainer_priv.sign(data))

    trust_pem = maintainer_priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")

    return {
        "registry": tmp_path,
        "package_dir": pkg,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "identity_path": identity_path,
        "creator_sig_path": creator_sig,
        "maintainer_sig_path": maintainer_sig,
        "trust": trust_pem,
        "fingerprint": fp,
    }


def _verify(spec: dict, *, require_maintainer: bool = False) -> None:
    _verify_package_manifest(
        spec["registry"],
        spec["package_dir"],
        spec["manifest"],
        spec["manifest_path"],
        spec["identity_path"],
        spec["creator_sig_path"],
        spec["maintainer_sig_path"],
        spec["trust"],
        entry_id="demo",
        expected_fingerprint=spec["fingerprint"],
        require_maintainer=require_maintainer,
    )


def test_valid_package_passes(tmp_path: Path) -> None:
    _verify(_make_package(tmp_path))
    _verify(_make_package(tmp_path), require_maintainer=True)


def test_schema_version_mismatch_rejected(tmp_path: Path) -> None:
    spec = _make_package(tmp_path, manifest_overrides={"schema_version": 2})
    with pytest.raises(ValueError, match="schema_version 不受支持"):
        _verify(spec)


def test_undeclared_payload_file_rejected(tmp_path: Path) -> None:
    spec = _make_package(tmp_path, extra_files={"extra.py": b"x = 1\n"})
    with pytest.raises(ValueError, match="文件集合不一致|未声明"):
        _verify(spec)


def test_missing_declared_file_rejected(tmp_path: Path) -> None:
    manifest_overrides = {"files": {"ghost.py": "sha256:" + hashlib.sha256(b"").hexdigest()}}
    spec = _make_package(tmp_path, manifest_overrides=manifest_overrides)
    with pytest.raises(ValueError, match="文件集合不一致|缺少 manifest 文件"):
        _verify(spec)


def test_symlink_rejected(tmp_path: Path, require_symlink: None) -> None:
    spec = _make_package(tmp_path, symlink=("shadow.py", "plugin.py"))
    with pytest.raises(ValueError, match="符号链接"):
        _verify(spec)


def test_private_key_filename_blacklisted(tmp_path: Path) -> None:
    spec = _make_package(tmp_path, extra_files={"id_rsa": b"PRIVATE KEY\n"})
    with pytest.raises(ValueError, match="私钥或凭据"):
        _verify(spec)


def test_private_key_suffix_blacklisted(tmp_path: Path) -> None:
    spec = _make_package(tmp_path, extra_files={"server.pem": b"key\n"})
    with pytest.raises(ValueError, match="私钥或凭据"):
        _verify(spec)


def test_manifest_fingerprint_mismatch_rejected(tmp_path: Path) -> None:
    spec = _make_package(
        tmp_path, manifest_overrides={"creator_fingerprint": "0" * 32}
    )
    with pytest.raises(ValueError, match="指纹"):
        _verify(spec)


def test_requested_username_mismatch_rejected(tmp_path: Path) -> None:
    spec = _make_package(
        tmp_path, manifest_overrides={"requested_username": "mallory"}
    )
    with pytest.raises(ValueError, match="requested_username"):
        _verify(spec)


def test_file_hash_content_mismatch_rejected(tmp_path: Path) -> None:
    wrong = hashlib.sha256(b"different").hexdigest()
    spec = _make_package(
        tmp_path, manifest_overrides={"files": {"plugin.py": f"sha256:{wrong}"}}
    )
    with pytest.raises(ValueError, match="文件哈希不一致"):
        _verify(spec)


def test_hash_format_must_be_sha256(tmp_path: Path) -> None:
    spec = _make_package(tmp_path, bad_hash_format=True)
    with pytest.raises(ValueError, match="哈希格式非法"):
        _verify(spec)


def test_tampered_creator_signature_rejected(tmp_path: Path) -> None:
    spec = _make_package(tmp_path, tamper_creator_sig=True)
    with pytest.raises(ValueError, match="创作者整包签名无效"):
        _verify(spec)
