#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""凭据扫描器的轻量回归门禁，不依赖第三方测试框架。"""

from __future__ import annotations

import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from scan_plugin import DEFAULT_ENTROPY_THRESHOLD, scan_plugin_dir, scan_text_content


def main() -> int:
    ordinary_source = (
        'def test_export_runs_through_real_capability_broker(tmp_path: Path) -> None:'
    )
    if scan_text_content(ordinary_source, DEFAULT_ENTROPY_THRESHOLD):
        raise SystemExit("FAIL scanner regression: ordinary source was treated as a credential")

    generic_secret = "M7vQ2xL9pR4sT8wY1zN6cK3jH5fD0bA"
    if not any(
        "高熵字符串" in issue
        for issue in scan_text_content(generic_secret, DEFAULT_ENTROPY_THRESHOLD)
    ):
        raise SystemExit("FAIL scanner regression: high-entropy token was not detected")

    github_token = "ghp_" + "A" * 36
    if not any(
        "GitHub Token" in issue
        for issue in scan_text_content(github_token, DEFAULT_ENTROPY_THRESHOLD)
    ):
        raise SystemExit("FAIL scanner regression: explicit token pattern was not detected")

    if not any(
        "凭据字段" in issue
        for issue in scan_text_content("api_key: example", DEFAULT_ENTROPY_THRESHOLD)
    ):
        raise SystemExit("FAIL scanner regression: credential field was not detected")

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "plugin.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "plugin.yaml").write_text("id: example\n", encoding="utf-8")
        (root / "market.yaml").write_text("name: Example\n", encoding="utf-8")
        manifest = root / "package.manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "files": {
                        "plugin.py": "sha256:example",
                        "plugin.yaml": "sha256:example",
                    }
                }
            ),
            encoding="utf-8",
        )
        unexpected = root / "unexpected.txt"
        unexpected.write_text("not declared\n", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            problem_count = scan_plugin_dir(root, manifest=manifest)
        if problem_count != 1:
            raise SystemExit(
                "FAIL scanner regression: signed manifest mapping did not reject an extra file"
            )
        unexpected.unlink()
        with redirect_stdout(io.StringIO()):
            problem_count = scan_plugin_dir(root, manifest=manifest)
        if problem_count:
            raise SystemExit(
                "FAIL scanner regression: generated market metadata was not handled safely"
            )

    print(
        "OK scanner regression: source false positives removed; credential and signed allowlist gates remain active"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
