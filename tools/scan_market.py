#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Scan every installed market package, including retained historical versions.

Only the registry-owned direct versions directory is split from the legacy
package. Standalone package scanning never acquires a versions exemption.
Signature verification remains a separate mandatory publish-check gate.
"""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from scan_plugin import scan_plugin_dir


def scan_market(registry: Path) -> int:
    errors = 0
    for kind, marker in (("plugins", "plugin.py"), ("templates", "template.yaml")):
        container = registry / kind
        if not container.is_dir():
            raise ValueError(f"Missing registry directory: {container}")
        # Reject links before traversing or copying any package data.
        for path in [container, *container.rglob("*")]:
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ValueError(f"Linked registry path rejected: {path}")
        for root in sorted(container.iterdir()):
            if not root.is_dir():
                if root.name == "README.md" and root.is_file():
                    with tempfile.TemporaryDirectory(prefix="market-readme-") as temporary:
                        shutil.copyfile(root, Path(temporary) / root.name)
                        errors += scan_plugin_dir(Path(temporary))
                    continue
                raise ValueError(f"Unexpected registry entry: {root}")
            versions = root / "versions"
            packages = []
            if versions.exists():
                if not versions.is_dir():
                    raise ValueError(f"Invalid versions container: {versions}")
                for package in sorted(versions.iterdir()):
                    if not package.is_dir() or not (package / marker).is_file():
                        raise ValueError(f"Invalid version package: {package}")
                    manifest = package / "package.manifest.json"
                    metadata = json.loads(manifest.read_text(encoding="utf-8"))
                    if not isinstance(metadata, dict) or not isinstance(metadata.get("files"), dict):
                        raise TypeError(f"Invalid package manifest: {package}")
                    if str(metadata.get("version")) != package.name:
                        raise ValueError(f"Version directory mismatch: {package}")
                    packages.append((package, manifest))
                if not packages:
                    raise ValueError(f"Empty versions container: {versions}")
                legacy_manifest = root / "package.manifest.json"
                if legacy_manifest.is_file():
                    legacy_metadata = json.loads(legacy_manifest.read_text(encoding="utf-8"))
                    if any(name == "versions" or name.startswith("versions/")
                           for name in legacy_metadata.get("files", {})):
                        raise ValueError(f"Legacy payload owns reserved versions path: {root}")
            if (root / marker).is_file():
                # Copy only the legacy package, never modify signed source bytes.
                with tempfile.TemporaryDirectory(prefix="market-scan-") as temporary:
                    view = Path(temporary) / root.name
                    view.mkdir()
                    for entry in root.iterdir():
                        if entry == versions:
                            continue
                        target = view / entry.name
                        if entry.is_dir():
                            shutil.copytree(entry, target)
                        else:
                            shutil.copyfile(entry, target)
                    manifest = view / "package.manifest.json"
                    if not manifest.is_file():
                        manifest = view / ("plugin.yaml" if kind == "plugins" else marker)
                    print(f"Scanning legacy package: {root}")
                    errors += scan_plugin_dir(view, manifest=manifest)
            else:
                if not packages:
                    raise ValueError(f"No package found: {root}")
                # A version-only container may contain only market metadata.
                with tempfile.TemporaryDirectory(prefix="market-container-") as temporary:
                    view = Path(temporary)
                    for entry in root.iterdir():
                        if entry == versions:
                            continue
                        if entry.name != "market.yaml" or not entry.is_file():
                            raise ValueError(f"Unexpected container file: {entry}")
                        shutil.copyfile(entry, view / entry.name)
                    errors += scan_plugin_dir(view)
            for package, manifest in packages:
                errors += scan_plugin_dir(package, manifest=manifest)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        errors = scan_market(args.registry)
    except (OSError, ValueError, TypeError) as exc:
        print(f"FAIL market scan: {exc}")
        return 1
    print(f"Market scan completed: {errors} problems")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
