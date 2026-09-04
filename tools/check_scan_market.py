#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Dependency-free multi-version scanner regression gate."""
import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from scan_market import scan_market
from scan_plugin import scan_plugin_dir


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "templates").mkdir()
        legacy = root / "plugins" / "example"
        new = legacy / "versions" / "0.4.0"
        new.mkdir(parents=True)
        for package, version in ((legacy, "0.3.0"), (new, "0.4.0")):
            (package / "plugin.py").write_text("VALUE = 1\n", encoding="utf-8")
            (package / "package.manifest.json").write_text(json.dumps({
                "version": version, "files": {"plugin.py": "sha256:example"}
            }), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            assert scan_market(root) == 0
            assert scan_plugin_dir(legacy, manifest=legacy / "package.manifest.json") > 0
            for package in (legacy, new):
                extra = package / "extra.txt"
                extra.write_text("unexpected\n", encoding="utf-8")
                assert scan_market(root) > 0
                extra.unlink()
                secret = package / "listing.md"
                secret.write_text("ghp_" + "A" * 36, encoding="utf-8")
                assert scan_market(root) > 0
                secret.unlink()
            rogue = legacy / "versions" / "stray.txt"
            rogue.write_text("not a package", encoding="utf-8")
            try:
                scan_market(root)
            except ValueError:
                pass
            else:
                raise AssertionError("Unowned versions file accepted")
            rogue.unlink()
            manifest = new / "package.manifest.json"
            original = manifest.read_text(encoding="utf-8")
            manifest.write_text(original.replace("0.4.0", "0.5.0"), encoding="utf-8")
            try:
                scan_market(root)
            except ValueError:
                pass
            else:
                raise AssertionError("Version mismatch accepted")
            manifest.write_text(original, encoding="utf-8")
            legacy_manifest = legacy / "package.manifest.json"
            old = legacy_manifest.read_text(encoding="utf-8")
            metadata = json.loads(old)
            metadata["files"]["versions/owned.txt"] = "sha256:example"
            legacy_manifest.write_text(json.dumps(metadata), encoding="utf-8")
            try:
                scan_market(root)
            except ValueError:
                pass
            else:
                raise AssertionError("Signed payload path silently excluded")
            legacy_manifest.write_text(old, encoding="utf-8")
            (new / "package.manifest.json").unlink()
            try:
                scan_market(root)
            except OSError:
                pass
            else:
                raise AssertionError("Unsigned version directory accepted")
    print("OK multi-version scanning: legacy/new files, secrets and boundaries")


if __name__ == "__main__":
    main()
