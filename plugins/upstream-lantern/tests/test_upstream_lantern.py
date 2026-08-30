import json
from pathlib import Path
from runpy import run_path
from urllib.parse import urlsplit

import pytest


def github(owner, repository):
    return "/".join(
        (
            "https:",
            "",
            "github.com",
            owner,
            repository,
        )
    )


def api(*parts):
    return "/".join(
        (
            "https:",
            "",
            "api.github.com",
            *parts,
        )
    )


@pytest.fixture(scope="module")
def plugin():
    root = Path(__file__)
    root = root.resolve()
    root = root.parents[1]
    path = root / "plugin.py"
    return run_path(str(path))


def seed(plugin, config):
    return plugin["handle"](
        "source.seed",
        {"config": config},
    )


def test_default_feeds_are_bounded_and_read_only(plugin):
    result = seed(
        plugin,
        {
            "seeds": [
                github(
                    "Starlife-creator",
                    "omnicrawler",
                )
            ]
        },
    )

    assert result["errors"] == []
    assert result["summary"] == {
        "repositories": 1,
        "requests": 2,
        "planned_requests": 2,
        "request_budget": 100,
        "preset": "",
        "feeds": ["repository", "releases"],
    }
    repository_url = api(
        "repos",
        "starlife-creator",
        "omnicrawler",
    )
    release_url = repository_url
    release_url += "/releases"
    release_url += "?per_page=30&page=1"
    actual_urls = [
        item["url"]
        for item in result["requests"]
    ]
    assert actual_urls == [
        repository_url,
        release_url,
    ]
    assert all(
        item["method"] == "GET"
        for item in result["requests"]
    )
    assert all(
        item["meta"]["read_only"] is True
        for item in result["requests"]
    )
    assert all(
        "Authorization" not in item["headers"]
        for item in result["requests"]
    )
    assert all(
        item["headers"]["X-GitHub-Api-Version"]
        == "2026-03-10"
        for item in result["requests"]
    )
    assert result["requests"][1]["meta"]["lantern_key"] == (
        "releases:starlife-creator/omnicrawler:page-1"
    )


def test_repository_forms_are_normalized_and_deduplicated(plugin):
    result = seed(
        plugin,
        {
            "seeds": [
                "Owner/Repo",
                github("owner", "repo.git"),
                api("repos", "OWNER", "REPO"),
            ],
            "params": {
                "feeds": ["tags"],
                "per_page": 1000,
            },
        },
    )

    assert result["errors"] == []
    assert len(result["requests"]) == 1
    expected = api(
        "repos",
        "owner",
        "repo",
        "tags",
    )
    expected += "?per_page=100&page=1"
    assert result["requests"][0]["url"] == expected
    assert result["warnings"] == [
        "source.params.per_page 已限制到允许的 1..100"
    ]


@pytest.mark.parametrize(
    "repository",
    [
        "http://github.com/owner/repo",
        "https://evil.example/owner/repo",
        "https://github.com/owner/repo/releases",
        "https://github.com/owner/repo?tab=readme",
        "owner/repo/extra",
        "owner with space/repo",
    ],
)
def test_noncanonical_or_unsafe_repository_is_rejected(
    plugin,
    repository,
):
    result = seed(
        plugin,
        {"seeds": [repository]},
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "source.seeds[0] 不是有效的 GitHub 仓库"
    ]


@pytest.mark.parametrize(
    "repository",
    [
        "https://user@github.com/owner/repo",
        "https://github.com:443/owner/repo",
    ],
)
def test_repository_url_rejects_userinfo_and_ports(
    plugin,
    repository,
):
    result = seed(
        plugin,
        {"seeds": [repository]},
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "source.seeds[0] 不是有效的 GitHub 仓库"
    ]


def test_advisory_query_is_explicit_encoded_and_deduplicated(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("pallets", "flask")],
            "params": {
                "feeds": ["advisories"],
                "per_page": 20,
                "severity": "HIGH",
                "advisory_packages": [
                    {
                        "ecosystem": "pip",
                        "name": "Flask",
                        "version": "3.0.0",
                    },
                    {
                        "ecosystem": "PIP",
                        "name": "flask",
                        "version": "3.0.0",
                    },
                    {
                        "ecosystem": "npm",
                        "name": "@scope/example",
                    },
                ],
            },
        },
    )

    assert result["errors"] == []
    assert len(result["requests"]) == 2
    first = api("advisories")
    first += "?affects="
    first += "Flask%403.0.0"
    first += "&ecosystem=pip"
    first += "&per_page=20"
    first += "&type=reviewed"
    first += "&severity=high"
    second = api("advisories")
    second += "?affects="
    second += "%40scope%2Fexample"
    second += "&ecosystem=npm"
    second += "&per_page=20"
    second += "&type=reviewed"
    second += "&severity=high"
    assert result["requests"][0]["url"] == first
    assert result["requests"][1]["url"] == second


def test_advisories_require_an_explicit_package_list(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {
                "feeds": [
                    "repository",
                    "advisories",
                ]
            },
        },
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "启用 advisories feed 时必须配置 source.params.advisory_packages"
    ]
    assert result["summary"]["planned_requests"] == 1


def test_invalid_package_entries_never_become_requests(plugin):
    result = seed(
        plugin,
        {
            "seeds": [],
            "params": {
                "feeds": ["advisories"],
                "advisory_packages": [
                    {
                        "ecosystem": "unknown-ecosystem",
                        "name": "demo",
                    },
                    {
                        "ecosystem": "pip",
                        "name": "",
                    },
                    "not-an-object",
                ],
            },
        },
    )

    assert result["requests"] == []
    assert len(result["errors"]) == 3


def test_hard_limits_fail_without_partial_repository_output(plugin):
    repositories = [
        github(
            "example",
            f"repo-{index}",
        )
        for index in range(21)
    ]
    result = seed(
        plugin,
        {"seeds": repositories},
    )

    assert result == {
        "requests": [],
        "errors": ["仓库数量不能超过 20"],
        "warnings": [],
    }


def test_pages_expand_only_paginated_repository_feeds(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {
                "feeds": [
                    "repository",
                    "releases",
                    "tags",
                    "commits",
                ],
                "per_page": 2,
                "pages": 3,
            },
        },
    )

    assert result["errors"] == []
    assert len(result["requests"]) == 10
    assert result["summary"]["planned_requests"] == 10
    page_meta = [
        item["meta"]["page"]
        for item in result["requests"]
        if "page" in item["meta"]
    ]
    assert page_meta == [
        1,
        2,
        3,
        1,
        2,
        3,
        1,
        2,
        3,
    ]


def test_commit_filters_are_validated_and_encoded(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {
                "feeds": ["commits"],
                "sha": "release/v1",
                "path": "src/demo file.py",
                "since": "2026-01-01T00:00:00Z",
                "until": "2026-02-01T00:00:00+08:00",
            },
        },
    )

    assert result["errors"] == []
    url = result["requests"][0]["url"]
    assert "sha=release%2Fv1" in url
    assert "path=src%2Fdemo+file.py" in url
    assert "since=2026-01-01T00%3A00%3A00Z" in url
    assert "until=2026-02-01T00%3A00%3A00%2B08%3A00" in url


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "since",
            "2026-01-01",
            "source.params.since 必须包含时区",
        ),
        (
            "until",
            "not-a-time",
            "source.params.until 必须是有效的 ISO 8601 时间",
        ),
        (
            "path",
            "bad\npath",
            "source.params.path 无效",
        ),
    ],
)
def test_invalid_commit_filter_fails_closed(
    plugin,
    field,
    value,
    message,
):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {
                "feeds": ["repository", "commits"],
                field: value,
            },
        },
    )

    assert result["requests"] == []
    assert result["errors"] == [message]
    assert result["summary"]["planned_requests"] == 2


def test_unknown_feed_and_severity_fail_closed(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {
                "feeds": ["repository", "typo"],
                "severity": "urgent",
            },
        },
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "source.params.feeds[1] 是未知 feed",
        "安全公告参数要求启用 advisories feed",
    ]


def test_reverse_commit_time_window_fails_closed(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {
                "feeds": ["commits"],
                "since": "2026-02-01T00:00:00Z",
                "until": "2026-01-01T00:00:00Z",
            },
        },
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "source.params.since 不能晚于 until"
    ]


def test_request_budget_rejects_the_entire_plan(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {
                "feeds": ["releases", "tags"],
                "pages": 3,
                "max_requests": 5,
            },
        },
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "计划请求数超过 source.params.max_requests：6 > 5"
    ]
    assert result["summary"]["planned_requests"] == 6
    assert result["summary"]["request_budget"] == 5


def test_numeric_bounds_are_clamped_with_visible_warnings(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {
                "feeds": ["releases"],
                "per_page": 0,
                "pages": 20,
                "max_requests": 1000,
            },
        },
    )

    assert result["errors"] == []
    assert len(result["requests"]) == 5
    assert result["warnings"] == [
        "source.params.per_page 已限制到允许的 1..100",
        "source.params.pages 已限制到允许的 1..5",
        "source.params.max_requests 已限制到允许的 1..100",
    ]


def test_maintenance_preset_adds_health_signals(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {"preset": "MAINTENANCE"},
        },
    )

    assert result["errors"] == []
    assert result["summary"]["preset"] == "maintenance"
    assert result["summary"]["feeds"] == [
        "repository",
        "releases",
        "commits",
        "community",
        "workflow_runs",
    ]
    assert len(result["requests"]) == 5
    signals = [
        item["meta"]["lantern_signal"]
        for item in result["requests"]
    ]
    assert signals == [
        "repository",
        "releases",
        "commits",
        "community",
        "workflow_runs",
    ]
    assert result["requests"][3]["url"] == api(
        "repos",
        "owner",
        "repo",
        "community",
        "profile",
    )
    workflow_url = api(
        "repos",
        "owner",
        "repo",
        "actions",
        "runs",
    )
    workflow_url += "?per_page=30&page=1"
    assert result["requests"][4]["url"] == workflow_url


def test_release_preset_keeps_simple_setup(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {"preset": "release"},
        },
    )

    assert result["errors"] == []
    assert result["summary"]["feeds"] == [
        "repository",
        "releases",
        "tags",
    ]


def test_security_preset_requires_explicit_packages(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {"preset": "security"},
        },
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "启用 advisories feed 时必须配置 source.params.advisory_packages"
    ]


def test_preset_and_manual_feeds_are_mutually_exclusive(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {
                "preset": "release",
                "feeds": ["repository"],
            },
        },
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "source.params.feeds 和 preset 不能同时配置"
    ]


def test_unknown_param_is_rejected_without_echoing_it(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {"token-looking-field": "secret"},
        },
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "source.params 第 1 个字段不受支持"
    ]
    assert "secret" not in str(result)


@pytest.mark.parametrize(
    "repository",
    [
        123,
        ["owner", "repo"],
        "拥有者/repo",
        "owner/仓库",
    ],
)
def test_repository_seed_requires_an_ascii_string(plugin, repository):
    result = seed(
        plugin,
        {"seeds": [repository]},
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "source.seeds[0] 不是有效的 GitHub 仓库"
    ]


@pytest.mark.parametrize(
    ("field", "value", "default"),
    [
        ("per_page", True, 30),
        ("pages", 1.5, 1),
        ("max_requests", False, 100),
    ],
)
def test_boolean_and_fractional_bounds_use_safe_defaults(
    plugin,
    field,
    value,
    default,
):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {field: value},
        },
    )

    assert result["errors"] == []
    assert result["warnings"] == [
        f"source.params.{field} 无效，已使用默认值 {default}"
    ]


def test_feed_entries_require_nonempty_strings(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {"feeds": ["repository", 1, ""]},
        },
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "source.params.feeds[1] 必须是字符串",
        "source.params.feeds[2] 是未知 feed",
    ]


def test_feed_specific_filters_cannot_be_silently_ignored(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {
                "feeds": ["repository"],
                "since": "2026-01-01T00:00:00Z",
                "advisory_packages": [],
            },
        },
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "提交筛选参数要求启用 commits feed",
        "安全公告参数要求启用 advisories feed",
    ]


def test_advisory_values_require_strings(plugin):
    result = seed(
        plugin,
        {
            "seeds": [github("owner", "repo")],
            "params": {
                "feeds": ["advisories"],
                "severity": 3,
                "advisory_packages": [
                    {
                        "ecosystem": "pip",
                        "name": "demo",
                        "version": 1,
                    }
                ],
            },
        },
    )

    assert result["requests"] == []
    assert result["errors"] == [
        "source.params.severity 必须是字符串",
        "advisory_packages[0].version 必须是字符串",
    ]


def test_result_is_deterministic_serializable_and_domain_scoped(plugin):
    config = {
        "seeds": [github("owner", "repo")],
        "params": {
            "preset": "maintenance",
            "pages": 2,
        },
    }
    first = seed(plugin, config)
    second = seed(plugin, config)

    assert first == second
    json.dumps(first, ensure_ascii=False)
    keys = [
        item["meta"]["lantern_key"]
        for item in first["requests"]
    ]
    assert len(keys) == len(set(keys))
    for item in first["requests"]:
        parsed = urlsplit(item["url"])
        assert parsed.scheme == "https"
        assert parsed.netloc == "api.github.com"
        assert parsed.username is None
        assert parsed.password is None


def test_unknown_operation_returns_protocol_object(plugin):
    result = plugin["handle"](
        "plugin.unknown",
        {},
    )

    assert result == {
        "error": "unsupported_operation",
        "operation": "plugin.unknown",
    }
