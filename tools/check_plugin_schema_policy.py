#!/usr/bin/env python3
"""Keep catalog and submission validators aligned on public plugin contracts.

P1-1/P2-3/P2-6/P2-7：权限、能力名、许可白名单、ID/用户名/域名正则两侧必须同集合
同形态——投稿器保持自包含（不 import 市场库），故由本策略脚本做双侧相等断言，
任一侧漂移即 CI 红。
"""

from __future__ import annotations

from catalog_lib import paths as market_paths
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
    PLUGIN_ID_RE as SUBMISSION_PLUGIN_ID_RE,
    TEMPLATE_ID_RE as SUBMISSION_TEMPLATE_ID_RE,
    USERNAME_RE as SUBMISSION_USERNAME_RE,
    DOMAIN_RE as SUBMISSION_DOMAIN_RE,
)

DECLARATIVE_TYPES = {"resource_provider", "view"}
DECLARATIVE_PERMISSIONS = {
    "resources:read",
    "surfaces:background",
    "render:local",
    "render:scripted",
}

# P2-7：双侧正则形态必须一致（投稿器自包含镜像副本，防止再次分叉出第二条规则轨）。
REGEX_PAIRS = (
    ("plugin_id", market_paths.PLUGIN_ID_RE, SUBMISSION_PLUGIN_ID_RE),
    ("template_id", market_paths.TEMPLATE_ID_RE, SUBMISSION_TEMPLATE_ID_RE),
    ("username", market_paths.USERNAME_RE, SUBMISSION_USERNAME_RE),
    ("domain", market_paths.DOMAIN_RE, SUBMISSION_DOMAIN_RE),
)


def main() -> int:
    missing_types = DECLARATIVE_TYPES - OFFICIAL_PLUGIN_TYPES
    missing_catalog = DECLARATIVE_PERMISSIONS - ALLOWED_PLUGIN_PERMISSIONS
    missing_submission = DECLARATIVE_PERMISSIONS - SUBMISSION_PERMISSIONS
    drift_permissions = ALLOWED_PLUGIN_PERMISSIONS ^ SUBMISSION_PERMISSIONS
    drift_capabilities = ALLOWED_CAPABILITIES ^ SUBMISSION_CAPABILITIES
    drift_licenses = LICENSE_ALLOWLIST ^ SUBMISSION_LICENSES
    drift_regexes = [
        name for name, market, submission in REGEX_PAIRS
        if market.pattern != submission.pattern
    ]
    if (
        missing_types
        or missing_catalog
        or missing_submission
        or drift_permissions
        or drift_capabilities
        or drift_licenses
        or drift_regexes
    ):
        raise SystemExit(
            "插件 schema 策略不一致: "
            f"types={sorted(missing_types)}, catalog={sorted(missing_catalog)}, "
            f"submission={sorted(missing_submission)}, "
            f"permissions_drift={sorted(drift_permissions)}, "
            f"capabilities_drift={sorted(drift_capabilities)}, "
            f"license_drift={sorted(drift_licenses)}, "
            f"regex_drift={sorted(drift_regexes)}"
        )
    print(
        "OK schema policy: types/permissions, capabilities, license allowlist "
        "and ID/domain regexes aligned"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
