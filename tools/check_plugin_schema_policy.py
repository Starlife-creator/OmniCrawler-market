#!/usr/bin/env python3
"""Keep catalog and submission validators aligned on public plugin capabilities."""

from __future__ import annotations

from catalog_lib.common import ALLOWED_PLUGIN_PERMISSIONS, OFFICIAL_PLUGIN_TYPES
from validate_submission import ALLOWED_PLUGIN_PERMISSIONS as SUBMISSION_PERMISSIONS

DECLARATIVE_TYPES = {"resource_provider", "view"}
DECLARATIVE_PERMISSIONS = {
    "resources:read",
    "surfaces:background",
    "render:local",
    "render:scripted",
}


def main() -> int:
    missing_types = DECLARATIVE_TYPES - OFFICIAL_PLUGIN_TYPES
    missing_catalog = DECLARATIVE_PERMISSIONS - ALLOWED_PLUGIN_PERMISSIONS
    missing_submission = DECLARATIVE_PERMISSIONS - SUBMISSION_PERMISSIONS
    if missing_types or missing_catalog or missing_submission:
        raise SystemExit(
            "插件 schema 策略不一致: "
            f"types={sorted(missing_types)}, catalog={sorted(missing_catalog)}, "
            f"submission={sorted(missing_submission)}"
        )
    print("OK schema policy: declarative resource/view capabilities aligned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
