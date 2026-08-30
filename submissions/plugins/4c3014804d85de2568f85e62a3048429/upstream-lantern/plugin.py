"""Upstream Lantern: bounded discovery for public GitHub upstream signals."""

from datetime import datetime
from urllib.parse import urlencode, urlsplit

PLUGIN_METADATA = {
    "name": "upstream-lantern",
    "version": "0.1.0",
    "api_version": 1,
    "description": "将 GitHub 项目转换为发布、提交、工作流和安全公告抓取请求",
    "plugin_types": ["source"],
    "permissions": [],
    "domains": ["api.github.com"],
    "input_files": [],
    "dependencies": [],
    "license": "MIT",
    "execution_mode": "subprocess",
    "min_core_version": "0.11.2",
    "source_url": "https://docs.github.com/en/rest",
}


_API_ROOT = "/".join(
    (
        "https:",
        "",
        "api.github.com",
    )
)
_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2026-03-10",
}
_DEFAULT_FEEDS = ("repository", "releases")
_FEEDS = frozenset(
    {
        "repository",
        "releases",
        "tags",
        "commits",
        "community",
        "workflow_runs",
        "advisories",
    }
)
_PRESETS = {
    "release": ("repository", "releases", "tags"),
    "maintenance": (
        "repository",
        "releases",
        "commits",
        "community",
        "workflow_runs",
    ),
    "security": ("repository", "releases", "advisories"),
    "complete": (
        "repository",
        "releases",
        "tags",
        "commits",
        "community",
        "workflow_runs",
        "advisories",
    ),
}
_PARAM_FIELDS = frozenset(
    {
        "advisory_packages",
        "feeds",
        "max_requests",
        "pages",
        "path",
        "per_page",
        "preset",
        "severity",
        "sha",
        "since",
        "until",
    }
)
_ECOSYSTEMS = frozenset(
    {
        "actions",
        "composer",
        "erlang",
        "go",
        "maven",
        "npm",
        "nuget",
        "other",
        "pip",
        "pub",
        "rubygems",
        "rust",
        "swift",
    }
)
_SEVERITIES = frozenset(
    {
        "unknown",
        "low",
        "medium",
        "high",
        "critical",
    }
)
_MAX_REPOSITORIES = 20
_MAX_ADVISORY_PACKAGES = 50
_MAX_PAGES = 5
_MAX_REQUESTS = 100


def _request(
    url,
    signal,
    *,
    repository="",
    package="",
    priority=0,
    page=None,
):
    """Build one read-only request using fixed, non-secret headers."""
    subject = repository or package or "global"
    key = f"{signal}:{subject}"
    meta = {
        "lantern_key": key,
        "lantern_signal": signal,
        "read_only": True,
    }
    if repository:
        meta["repository"] = repository
    if package:
        meta["package"] = package
    if page is not None:
        meta["page"] = page
        meta["lantern_key"] = f"{key}:page-{page}"
    return {
        "url": url,
        "method": "GET",
        "headers": dict(_API_HEADERS),
        "priority": priority,
        "meta": meta,
    }


def _safe_owner(value):
    return (
        0 < len(value) <= 100
        and value not in {".", ".."}
        and value.isascii()
        and all(character.isalnum() or character == "-" for character in value)
    )


def _safe_repository(value):
    return (
        0 < len(value) <= 100
        and value not in {".", ".."}
        and value.isascii()
        and all(character.isalnum() or character in "-_." for character in value)
    )


def _parse_repository(seed):
    """Return a normalized owner/repository pair without accepting arbitrary hosts."""
    if not isinstance(seed, str):
        return None
    raw = seed.strip()
    if not raw:
        return None

    if "://" in raw:
        parsed = urlsplit(raw)
        if parsed.scheme.casefold() != "https" or parsed.query or parsed.fragment:
            return None
        host = (parsed.netloc or "").casefold()
        parts = [part for part in parsed.path.split("/") if part]
        if host in {"github.com", "www.github.com"}:
            if len(parts) != 2:
                return None
            owner, repository = parts
        elif host == "api.github.com":
            if len(parts) != 3 or parts[0].casefold() != "repos":
                return None
            owner, repository = parts[1:]
        else:
            return None
    else:
        parts = [part for part in raw.split("/") if part]
        if len(parts) != 2:
            return None
        owner, repository = parts

    if repository.casefold().endswith(".git"):
        repository = repository[:-4]
    if not _safe_owner(owner) or not _safe_repository(repository):
        return None
    return owner.casefold(), repository.casefold()


def _bounded_integer(
    value,
    *,
    default,
    minimum,
    maximum,
    field,
    warnings,
):
    if isinstance(value, bool):
        warnings.append(f"source.params.{field} 无效，已使用默认值 {default}")
        return default
    if isinstance(value, float) and not value.is_integer():
        warnings.append(f"source.params.{field} 无效，已使用默认值 {default}")
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        warnings.append(f"source.params.{field} 无效，已使用默认值 {default}")
        return default
    bounded = min(maximum, max(minimum, parsed))
    if bounded != parsed:
        warnings.append(
            f"source.params.{field} 已限制到允许的 {minimum}..{maximum}"
        )
    return bounded


def _selected_feeds(value, preset, errors):
    has_preset = preset is not None and preset != ""
    if value is not None and has_preset:
        errors.append("source.params.feeds 和 preset 不能同时配置")
        return ()
    if has_preset:
        if not isinstance(preset, str):
            errors.append("source.params.preset 必须是字符串")
            return ()
        name = preset.strip().casefold()
        selected = _PRESETS.get(name)
        if selected is None:
            errors.append("source.params.preset 无效")
            return ()
        return selected
    if value is None:
        return _DEFAULT_FEEDS
    if not isinstance(value, list):
        errors.append("source.params.feeds 必须是列表")
        return ()
    if not value:
        errors.append("source.params.feeds 至少需要一个 feed")
        return ()
    selected = []
    if len(value) > 20:
        errors.append("source.params.feeds 项目数不能超过 20")
        return ()
    for index, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"source.params.feeds[{index}] 必须是字符串")
            continue
        name = item.strip().casefold()
        if name in _FEEDS and name not in selected:
            selected.append(name)
        elif name not in selected:
            errors.append(f"source.params.feeds[{index}] 是未知 feed")
    return tuple(selected)


def _validate_param_fields(params, errors):
    for index, field in enumerate(params):
        if field not in _PARAM_FIELDS:
            errors.append(f"source.params 第 {index + 1} 个字段不受支持")


def _safe_query_text(value, maximum):
    return (
        isinstance(value, str)
        and len(value) <= maximum
        and not any(
            ord(character) < 32 or ord(character) == 127
            for character in value
        )
    )


def _timestamp(value, field, errors):
    if value is None or value == "":
        return "", None
    if not _safe_query_text(value, 40):
        errors.append(f"source.params.{field} 必须是有效的 ISO 8601 时间")
        return "", None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        errors.append(f"source.params.{field} 必须是有效的 ISO 8601 时间")
        return "", None
    if parsed.tzinfo is None:
        errors.append(f"source.params.{field} 必须包含时区")
        return "", None
    return value, parsed


def _commit_filters(params, errors):
    filters = {}
    for field, maximum in (("sha", 200), ("path", 500)):
        value = params.get(field, "")
        if value == "":
            continue
        if not _safe_query_text(value, maximum):
            errors.append(f"source.params.{field} 无效")
            continue
        filters[field] = value
    timestamps = {}
    for field in ("since", "until"):
        value, parsed = _timestamp(params.get(field), field, errors)
        if value:
            filters[field] = value
            timestamps[field] = parsed
    if (
        "since" in timestamps
        and "until" in timestamps
        and timestamps["since"] > timestamps["until"]
    ):
        errors.append("source.params.since 不能晚于 until")
    return filters


def _is_configured(value):
    return value is not None and value != ""


def _validate_feed_params(params, feeds, errors):
    commit_fields = ("path", "sha", "since", "until")
    has_commit_filter = any(
        _is_configured(params.get(field))
        for field in commit_fields
    )
    if "commits" not in feeds and has_commit_filter:
        errors.append("提交筛选参数要求启用 commits feed")
    has_advisory_filter = (
        params.get("advisory_packages") is not None
        or _is_configured(params.get("severity"))
    )
    if "advisories" not in feeds and has_advisory_filter:
        errors.append("安全公告参数要求启用 advisories feed")


def _paged_request(
    requests,
    base,
    signal,
    repository,
    priority,
    per_page,
    pages,
    extra_query=None,
):
    for page in range(1, pages + 1):
        query = {
            "per_page": per_page,
            "page": page,
        }
        if extra_query:
            query.update(extra_query)
        requests.append(
            _request(
                f"{base}?{urlencode(query)}",
                signal,
                repository=repository,
                priority=priority,
                page=page,
            )
        )


def _repository_requests(
    repositories,
    feeds,
    per_page,
    pages,
    commit_filters,
):
    requests = []
    for owner, repository in repositories:
        name = f"{owner}/{repository}"
        base = f"{_API_ROOT}/repos/{owner}/{repository}"
        if "repository" in feeds:
            requests.append(_request(base, "repository", repository=name, priority=30))
        if "releases" in feeds:
            _paged_request(
                requests,
                f"{base}/releases",
                "releases",
                name,
                20,
                per_page,
                pages,
            )
        if "tags" in feeds:
            _paged_request(
                requests,
                f"{base}/tags",
                "tags",
                name,
                10,
                per_page,
                pages,
            )
        if "commits" in feeds:
            _paged_request(
                requests,
                f"{base}/commits",
                "commits",
                name,
                15,
                per_page,
                pages,
                commit_filters,
            )
        if "community" in feeds:
            requests.append(
                _request(
                    f"{base}/community/profile",
                    "community",
                    repository=name,
                    priority=35,
                )
            )
        if "workflow_runs" in feeds:
            _paged_request(
                requests,
                f"{base}/actions/runs",
                "workflow_runs",
                name,
                25,
                per_page,
                pages,
            )
    return requests


def _advisory_requests(packages, feeds, per_page, severity, errors):
    if "advisories" not in feeds:
        return []
    if packages is None:
        errors.append("启用 advisories feed 时必须配置 source.params.advisory_packages")
        return []
    if not isinstance(packages, list):
        errors.append("source.params.advisory_packages 必须是列表")
        return []
    if not packages:
        errors.append("source.params.advisory_packages 不能为空")
        return []
    if (
        len(packages)
        > _MAX_ADVISORY_PACKAGES
    ):
        errors.append(f"安全公告包数量不能超过 {_MAX_ADVISORY_PACKAGES}")
        return []

    requests = []
    seen = set()
    for index, item in enumerate(packages):
        if not isinstance(item, dict):
            errors.append(f"advisory_packages[{index}] 必须是对象")
            continue
        ecosystem_value = item.get("ecosystem", "")
        name_value = item.get("name", "")
        version_value = item.get("version", "")
        if not isinstance(ecosystem_value, str):
            errors.append(f"advisory_packages[{index}].ecosystem 必须是字符串")
            continue
        if not isinstance(name_value, str):
            errors.append(f"advisory_packages[{index}].name 必须是字符串")
            continue
        if not isinstance(version_value, str):
            errors.append(f"advisory_packages[{index}].version 必须是字符串")
            continue
        ecosystem = ecosystem_value.strip().casefold()
        name = name_value.strip()
        version = version_value.strip()
        if ecosystem not in _ECOSYSTEMS:
            errors.append(f"advisory_packages[{index}].ecosystem 不受支持")
            continue
        if not name or not _safe_query_text(name, 200):
            errors.append(f"advisory_packages[{index}].name 无效")
            continue
        if not _safe_query_text(version, 100):
            errors.append(f"advisory_packages[{index}].version 无效")
            continue
        affects = f"{name}@{version}" if version else name
        identity = (ecosystem, affects.casefold(), severity)
        if identity in seen:
            continue
        seen.add(identity)
        query = {
            "affects": affects,
            "ecosystem": ecosystem,
            "per_page": per_page,
            "type": "reviewed",
        }
        if severity:
            query["severity"] = severity
        requests.append(
            _request(
                f"{_API_ROOT}/advisories?{urlencode(query)}",
                "advisories",
                package=f"{ecosystem}:{affects}",
                priority=40,
            )
        )
    return requests


def _seed(payload):
    warnings = []
    errors = []
    if not isinstance(payload, dict):
        return {"requests": [], "errors": ["payload 必须是对象"], "warnings": []}
    config = payload.get("config", {})
    if not isinstance(config, dict):
        return {"requests": [], "errors": ["payload.config 必须是对象"], "warnings": []}

    seeds = config.get("seeds", [])
    if not isinstance(seeds, list):
        return {"requests": [], "errors": ["source.seeds 必须是列表"], "warnings": []}
    if len(seeds) > _MAX_REPOSITORIES:
        return {
            "requests": [],
            "errors": [f"仓库数量不能超过 {_MAX_REPOSITORIES}"],
            "warnings": [],
        }

    repositories = []
    seen_repositories = set()
    for index, seed in enumerate(seeds):
        parsed = _parse_repository(seed)
        if parsed is None:
            errors.append(f"source.seeds[{index}] 不是有效的 GitHub 仓库")
            continue
        if parsed not in seen_repositories:
            repositories.append(parsed)
            seen_repositories.add(parsed)

    params = config.get("params", {})
    if not isinstance(params, dict):
        errors.append("source.params 必须是对象")
        params = {}
    _validate_param_fields(params, errors)
    feeds = _selected_feeds(
        params.get("feeds"),
        params.get("preset"),
        errors,
    )
    _validate_feed_params(params, feeds, errors)
    per_page = _bounded_integer(
        params.get("per_page", 30),
        default=30,
        minimum=1,
        maximum=100,
        field="per_page",
        warnings=warnings,
    )
    pages = _bounded_integer(
        params.get("pages", 1),
        default=1,
        minimum=1,
        maximum=_MAX_PAGES,
        field="pages",
        warnings=warnings,
    )
    max_requests = _bounded_integer(
        params.get("max_requests", _MAX_REQUESTS),
        default=_MAX_REQUESTS,
        minimum=1,
        maximum=_MAX_REQUESTS,
        field="max_requests",
        warnings=warnings,
    )
    severity_value = params.get("severity", "")
    if "advisories" not in feeds:
        severity = ""
    elif not isinstance(severity_value, str):
        errors.append("source.params.severity 必须是字符串")
        severity = ""
    else:
        severity = severity_value.strip().casefold()
    if severity and severity not in _SEVERITIES:
        errors.append("source.params.severity 无效")
    commit_filters = (
        _commit_filters(params, errors)
        if "commits" in feeds
        else {}
    )

    requests = _repository_requests(
        repositories,
        feeds,
        per_page,
        pages,
        commit_filters,
    )
    requests.extend(
        _advisory_requests(
            params.get("advisory_packages"),
            feeds,
            per_page,
            severity,
            errors,
        )
    )
    planned_requests = len(requests)
    if planned_requests > max_requests:
        errors.append(
            "计划请求数超过 source.params.max_requests："
            f"{planned_requests} > {max_requests}"
        )
    if errors:
        requests = []
    return {
        "requests": requests,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "repositories": len(repositories),
            "requests": len(requests),
            "planned_requests": planned_requests,
            "request_budget": max_requests,
            "preset": (
                params.get("preset", "").strip().casefold()
                if isinstance(params.get("preset", ""), str)
                else ""
            ),
            "feeds": list(feeds),
        },
    }


def handle(operation, payload):
    """Contract 2 entry point. It performs no network or filesystem access."""
    if operation == "source.seed":
        return _seed(payload)
    return {"error": "unsupported_operation", "operation": str(operation)}
