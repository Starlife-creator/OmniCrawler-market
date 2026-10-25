#!/usr/bin/env python3
"""Keep catalog and submission validators aligned on public plugin contracts.

P1-1/P2-3/P2-6：权限、能力名、许可白名单两侧必须同集合——投稿器保持自包含
（不 import 市场库），故由本策略脚本做双侧相等断言，任一侧漂移即 CI 红。
"""

from __future__ import annotations

from catalog_lib.common import (
    ALLOWED_CAPABILITIES,
    ALLOWED_PLUGIN_PERMISSIONS,
    LICENSE_ALLOWLIST,
    OFFICIAL_PLUGIN_TYPES,
)
from validate_submission import (
    ALLOWED_CAPABILITIES as SUBMISSION_CAPABILITIES,
    ALLOWED_PLUGIN_PERMISSIONS as SUBMISSION_PERMISSIONS,
    LICENSE_ALLOWLIST as SUBMISSION_LICENSES,
)

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
    drift_permissions = ALLOWED_PLUGIN_PERMISSIONS ^ SUBMISSION_PERMISSIONS
    drift_capabilities = ALLOWED_CAPABILITIES ^ SUBMISSION_CAPABILITIES
    drift_licenses = LICENSE_ALLOWLIST ^ SUBMISSION_LICENSES
    if (
        missing_types
        or missing_catalog
        or missing_submission
        or drift_permissions
        or drift_capabilities
        or drift_licenses
    ):
        raise SystemExit(
            "插件 schema 策略不一致: "
            f"types={sorted(missing_types)}, catalog={sorted(missing_catalog)}, "
            f"submission={sorted(missing_submission)}, "
            f"permissions_drift={sorted(drift_permissions)}, "
            f"capabilities_drift={sorted(drift_capabilities)}, "
            f"license_drift={sorted(drift_licenses)}"
        )
    print("OK schema policy: declarative types/permissions, capabilities and license allowlist aligned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
