"""Upstream Lantern: bounded discovery for public GitHub upstream signals."""

import base64
import hashlib
import json
from datetime import datetime
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

PLUGIN_METADATA = {
    "name": "upstream-lantern",
    "version": "0.3.0",
    "api_version": 1,
    "description": "将 GitHub 项目转换为发布、提交、工作流和安全公告抓取请求",
    "plugin_types": ["source", "extractor"],
    "permissions": ["state:read", "state:write"],
    "state_schema_version": 1,
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
        "adaptive_pagination",
        "track_changes",
        "initial_policy",
        "include_prereleases",
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
    for field in ("adaptive_pagination", "track_changes", "include_prereleases"):
        if field in params and not isinstance(params[field], bool):
            errors.append(f"source.params.{field} 必须是布尔值")
    if not isinstance(params.get("initial_policy", "notify"), str) or params.get("initial_policy", "notify") not in {"notify", "baseline"}:
        errors.append("source.params.initial_policy 必须为 notify 或 baseline")
    planned_requests = len(requests)
    if not errors:
        for request in requests:
            request["meta"].update({"track_changes": bool(params.get("track_changes", False)),
                "adaptive_pagination": bool(params.get("adaptive_pagination", False)),
                "page_limit": pages, "per_page": per_page,
                "initial_policy": params.get("initial_policy", "notify"),
                "include_prereleases": params.get("include_prereleases", True)})
        if params.get("adaptive_pagination"):
            requests = [r for r in requests if r["meta"].get("page", 1) == 1]
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


def _extract(payload):
    result = payload.get("result") or {}
    request = result.get("request") or {}
    meta = request.get("meta") or result.get("meta") or {}
    source_url = str(result.get("final_url") or result.get("url") or request.get("url") or "")
    status = int(result.get("status") or 0)
    signal = str(meta.get("lantern_signal") or "unknown")
    subject = str(meta.get("repository") or meta.get("package") or "")
    if status == 304:
        return {"records": [], "requests": [], "summary": {"status": "revalidated", "complete": True}}
    if not 200 <= status < 300:
        error = "rate_limited_or_forbidden" if status in {403, 429} else "not_found_or_private" if status == 404 else "http_error"
        return {"records": [{"source_url": source_url, "record_type": "upstream_error",
            "data": {"signal": signal, "subject": subject, "http_status": status, "reason": error, "complete": False}}], "requests": []}
    try:
        data = json.loads(base64.b64decode(str(result.get("body_b64") or ""), validate=True).decode("utf-8"))
    except (ValueError, TypeError, UnicodeError):
        return {"records": [{"source_url": source_url, "record_type": "upstream_error", "data": {"signal": signal, "reason": "invalid_json", "complete": False}}], "requests": []}
    raw_items = data.get("workflow_runs", []) if signal == "workflow_runs" and isinstance(data, dict) else data
    items = raw_items if isinstance(raw_items, list) else [raw_items]
    records = []
    for item in items[:100]:
        if not isinstance(item, dict):
            continue
        if signal == "releases" and (item.get("draft") or (item.get("prerelease") and not meta.get("include_prereleases", True))):
            continue
        identity = str(item.get("id") or item.get("ghsa_id") or item.get("sha") or item.get("tag_name") or item.get("name") or subject)
        commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
        concise = {"signal": signal, "subject": subject, "id": identity,
            "title": str(item.get("name") or item.get("title") or item.get("summary") or item.get("tag_name") or commit.get("message", ""))[:500],
            "url": str(item.get("html_url") or "")[:1000]}
        for field in ("tag_name", "published_at", "prerelease", "draft", "status", "conclusion", "severity", "score", "default_branch", "archived"):
            if field in item:
                concise[field] = item[field]
        digest = hashlib.sha256(json.dumps(concise, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        change = "untracked"
        recovered = False
        policy = {"initial_policy": meta.get("initial_policy", "notify"), "include_prereleases": bool(meta.get("include_prereleases", True))}
        policy_id = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
        entity = signal + ":" + subject.casefold() + ":" + identity
        if meta.get("track_changes"):
            try:
                import omnicrawler_sdk
                key = "lantern.v3." + hashlib.sha256((entity + ":" + policy_id).encode()).hexdigest()
                previous = omnicrawler_sdk.call("state.get", {"key": key})
                old = previous.get("value") if previous.get("found") else None
                if old is None and policy == {"initial_policy": "notify", "include_prereleases": True}:
                    # Preserve existing default-policy observations on upgrade.
                    legacy_key = "lantern." + hashlib.sha256((signal + ":" + subject + ":" + identity).encode()).hexdigest()
                    legacy = omnicrawler_sdk.call("state.get", {"key": legacy_key})
                    old = legacy.get("value") if legacy.get("found") else None
                old_digest = old.get("sha256") if isinstance(old, dict) else old
                change = "new" if not old_digest else "unchanged" if old_digest == digest else "changed"
                recovered = bool(signal == "workflow_runs" and isinstance(old, dict) and
                                 old.get("conclusion") in {"failure", "timed_out", "action_required"} and item.get("conclusion") == "success")
                omnicrawler_sdk.call("state.set", {"key": key, "value": {"sha256": digest, "conclusion": item.get("conclusion")}})
            except Exception:
                change = "tracking_unavailable"
        concise["change"] = change
        concise["event_id"] = hashlib.sha256((entity + ":" + digest).encode()).hexdigest()
        concise["policy_id"] = policy_id
        concise["event_kind"] = "recovery" if recovered else "observation"
        concise["initial_baseline"] = change == "new" and policy["initial_policy"] == "baseline"
        concise["attention"] = not concise["initial_baseline"] and change in {"new", "changed"} and (signal in {"releases", "advisories"} or recovered or signal == "workflow_runs" and item.get("conclusion") in {"failure", "timed_out", "action_required"})
        records.append({"source_url": source_url, "record_type": "upstream_signal", "data": concise,
            "evidence": {"method": "upstream-lantern-v2", "sha256": digest}})
    requests = []
    page = int(meta.get("page") or 1)
    limit = max(1, min(5, int(meta.get("page_limit") or 1)))
    per_page = max(1, min(100, int(meta.get("per_page") or 30)))
    has_more = isinstance(raw_items, list) and len(raw_items) >= per_page
    if meta.get("adaptive_pagination") and signal in {"releases", "tags", "commits", "workflow_runs"} and has_more and page < limit:
        parts = urlsplit(str(request.get("url") or source_url))
        # Follow only a generated endpoint; never trust server-provided Link targets.
        owner_repo = _parse_repository(subject)
        suffix = {"releases": "/releases", "tags": "/tags", "commits": "/commits", "workflow_runs": "/actions/runs"}[signal]
        expected = "/repos/" + subject + suffix
        if owner_repo and parts.scheme == "https" and parts.netloc == "api.github.com" and parts.path == expected:
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            query["page"] = str(page + 1)
            following = _request(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), "")), signal, repository=subject, page=page + 1)
            following["meta"].update({**meta, "page": page + 1, "lantern_key": f"{signal}:{subject}:page-{page + 1}"})
            requests.append(following)
    return {"records": records, "requests": requests, "artifact_path": None,
        "summary": {"signal": signal, "records": len(records), "page": page, "complete": not has_more,
            "page_limit_reached": has_more and page >= limit, "next_page_planned": bool(requests)}}


def handle(operation, payload):
    """Contract 2 entry point; HTTP remains entirely host-owned."""
    if operation == "source.seed":
        return _seed(payload)
    if operation == "extractor.process":
        return _extract(payload if isinstance(payload, dict) else {})
    return {"error": "unsupported_operation", "operation": str(operation)}
