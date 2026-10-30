"""P1-4：build_catalog 目录组装失败路径负样例——重复 ID、声明文件缺失、
双签名轨缺失、作者指纹归属不符。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from catalog_lib.build import build_catalog


def _fixture(
    tmp_path: Path,
    *,
    plugin_dirs: dict[str, dict] | None = None,
    author_fingerprint: str | None = None,
) -> Path:
    """组装最小可构建目录；plugin_dirs 为 {目录名: market.yaml 覆盖}。"""
    maintainer = Ed25519PrivateKey.generate()
    (tmp_path / "keys").mkdir()
    (tmp_path / "keys" / "plugin_trust.pub.pem").write_bytes(
        maintainer.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    creator = Ed25519PrivateKey.generate()
    creator_fp = hashlib.sha256(creator.public_key().public_bytes_raw()).hexdigest()[:32]

    authors = tmp_path / "authors"
    authors.mkdir()
    (authors / "alice.yaml").write_text(
        yaml.safe_dump({
            "market_handle": "alice",
            "username": "alice",
            "fingerprint": creator_fp,
            "roles": ["publisher"],
        }, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    plugin_dirs = plugin_dirs or {"demo": {}}
    for dirname, overrides in plugin_dirs.items():
        folder = tmp_path / "plugins" / dirname
        folder.mkdir(parents=True)
        plugin_bytes = b"PLUGIN_METADATA = {'name': 'demo'}\n"
        (folder / "plugin.py").write_bytes(plugin_bytes)
        (folder / "listing.md").write_text("# Demo\n", encoding="utf-8")
        (folder / "plugin.py.sig").write_bytes(maintainer.sign(plugin_bytes))

        manifest = {
            "id": overrides.pop("id", "demo"),
            "name": "Demo",
            "version": "1.0.0",
            "publisher": "alice",
            "category": "source",
            "summary": "demo plugin",
            "description_file": f"plugins/{dirname}/listing.md",
            "plugin_file": f"plugins/{dirname}/plugin.py",
            "signature_file": f"plugins/{dirname}/plugin.py.sig",
            "signature_algorithm": "ed25519",
            "permissions": ["records:read"],
            "compatible_core": ">=1.0.0",
            "license": "MIT",
            "plugin_types": ["processor"],
            "author_fingerprint": author_fingerprint or creator_fp,
        }
        manifest.update(overrides)
        (folder / "market.yaml").write_text(
            yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return tmp_path


def test_minimal_registry_builds_catalog(tmp_path: Path) -> None:
    registry = _fixture(tmp_path)
    catalog = build_catalog(registry, sequence=1)
    assert [plugin["id"] for plugin in catalog["plugins"]] == ["demo"]
    assert catalog["sequence"] == 1


def test_duplicate_plugin_id_rejected(tmp_path: Path) -> None:
    registry = _fixture(tmp_path, plugin_dirs={"alpha": {"id": "demo"}, "beta": {"id": "demo"}})
    with pytest.raises(ValueError, match="重复插件 ID"):
        build_catalog(registry)


def test_missing_declared_plugin_file_rejected(tmp_path: Path) -> None:
    registry = _fixture(
        tmp_path,
        plugin_dirs={"demo": {"plugin_file": "plugins/demo/ghost.py"}},
    )
    with pytest.raises(ValueError, match="不存在"):
        build_catalog(registry)


def test_missing_signature_rail_rejected(tmp_path: Path) -> None:
    registry = _fixture(
        tmp_path,
        plugin_dirs={"demo": {"signature_file": None}},
    )
    with pytest.raises(ValueError, match="签名轨"):
        build_catalog(registry)


def test_author_fingerprint_mismatch_rejected(tmp_path: Path) -> None:
    registry = _fixture(tmp_path, author_fingerprint="0" * 32)
    with pytest.raises(ValueError, match="指纹"):
        build_catalog(registry)
