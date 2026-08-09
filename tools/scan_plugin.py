#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# 本工具代码以 MIT License 授权（见 tools/LICENSE）。
"""发布前安全扫描（git-as-registry 生态工具，随 registry/ 自包含）。

用法：
  python registry/tools/scan_plugin.py scan <plugin_dir>... [--manifest <yaml>]
       [--json] [--entropy-threshold 4.5]

扫描步骤（对齐 Helios 发布前五步扫描，适配 OmniCrawler 插件目录形态）：
  1. 敏感文件黑名单：.env / *.pem / *.key / *.p12 / *.pfx / id_rsa 等；
  2. 高熵字符串检测：文本文件中 Shannon 熵 > 阈值的连续 16+ 字符；
  3. API Token 模式匹配：AWS / GitHub / Slack / OpenAI / 私钥头；
  4. 私钥/凭据字段检测：YAML/JSON 中 private_key / secret_key / api_key 等键；
  5. 允许列表（可选 --manifest）：清单声明 files 之外存在文件 → 报错。

退出码：0 干净；1 发现问题。
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import yaml

SENSITIVE_NAMES = {
    ".env",
    "credentials.json",
    "secrets.yaml",
    "key_store.yaml",
    "key_store.json",
    "id_rsa",
    "id_rsa.pub",
    "config.ini",
    ".npmrc",
    ".pypirc",
    ".netrc",
}
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".ppk", ".secret", ".gpg")
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".sig", ".md")
DEFAULT_ENTROPY_THRESHOLD = 4.5
MIN_TOKEN_LEN = 16

_TOKEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS Access Key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub Token", re.compile(r"\bghp_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("OpenAI Key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("私钥头", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b")),
]

_SECRET_FIELD_RE = re.compile(
    r"^\s*(private_key|secret_key|api_key|apikey|access_key|access_token|"
    r"client_secret|auth_token|password|passwd)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


def _iter_files(plugin_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in plugin_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(plugin_dir).parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def _shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts: dict[int, int] = {}
    for byte in data:
        counts[byte] = counts.get(byte, 0) + 1
    length = len(data)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _high_entropy_tokens(text: str, threshold: float) -> list[str]:
    tokens: list[str] = []
    for match in re.finditer(r"[ -~]{16,}", text):
        token = match.group()
        if _shannon_entropy(token.encode("utf-8", "ignore")) > threshold:
            tokens.append(token)
    return tokens


def scan_text_content(text: str, threshold: float) -> list[str]:
    """对单个文本内容执行高熵 + Token 模式扫描，返回问题描述列表。"""
    problems: list[str] = []
    for token in _high_entropy_tokens(text, threshold):
        problems.append(f"高熵字符串（熵>{threshold}）: {token[:64]}...")
    for name, pattern in _TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            problems.append(f"疑似 {name}: {match.group(0)[:48]}")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if _SECRET_FIELD_RE.match(line):
            problems.append(f"疑似私钥/凭据字段（第 {line_no} 行）: {line.strip()[:64]}")
    return problems


def _scan_file(path: Path, *, threshold: float) -> list[str]:
    if path.suffix in (".json", ".yaml", ".yml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            problems = _scan_mapping_fields(data, path)
        except (yaml.YAMLError, UnicodeDecodeError):
            problems = []
        problems += scan_text_content(path.read_text(encoding="utf-8", errors="ignore"), threshold)
        return problems
    if path.suffix in (".py", ".txt", ".cfg", ".ini", ".toml", ".sh", ".bat", ".html", ".js"):
        return scan_text_content(path.read_text(encoding="utf-8", errors="ignore"), threshold)
    return []


def _scan_mapping_fields(data: Any, path: Path) -> list[str]:
    problems: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if _SECRET_FIELD_RE.match(f"{key}:"):
                problems.append(f"{path.name}: 包含疑似私钥字段 {key}")
            problems += _scan_mapping_fields(value, path)
    elif isinstance(data, list):
        for item in data:
            problems += _scan_mapping_fields(item, path)
    return problems


def _scan_allowlist(plugin_dir: Path, manifest_path: Path | None) -> tuple[list[str], list[str]]:
    """返回 (警告, 错误)：manifest 声明 files 之外存在文件 → 错误；未声明 files → 警告。"""
    warnings: list[str] = []
    errors: list[str] = []
    if manifest_path is None or not manifest_path.is_file():
        return warnings, errors
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    allowed = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(allowed, list):
        return ["manifest 未声明 files 允许列表（建议声明，从源头杜绝误打包敏感文件）"], errors
    allowed_set = {str(item) for item in allowed}
    for path in _iter_files(plugin_dir):
        if path.resolve() == manifest_path.resolve():
            continue  # 清单自身是元数据，不参与打包
        rel = path.relative_to(plugin_dir).as_posix()
        if rel not in allowed_set:
            errors.append(f"允许列表外文件（manifest 未声明）: {rel}")
    return warnings, errors


def scan_plugin_dir(
    plugin_dir: Path,
    *,
    manifest: Path | None = None,
    entropy_threshold: float = DEFAULT_ENTROPY_THRESHOLD,
) -> int:
    """扫描一个插件目录，打印问题；返回问题数（警告不计入失败）。"""
    if not plugin_dir.is_dir():
        print(f"[FAIL] 目录不存在: {plugin_dir}")
        return 1
    errors: list[str] = []
    warnings: list[str] = []
    for path in _iter_files(plugin_dir):
        name = path.name
        if name in SENSITIVE_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
            errors.append(f"敏感文件（黑名单）: {path.relative_to(plugin_dir)}")
            continue
        if name.startswith("id_rsa"):
            errors.append(f"敏感文件（id_rsa 系列）: {path.relative_to(plugin_dir)}")
            continue
        for issue in _scan_file(path, threshold=entropy_threshold):
            errors.append(f"{path.relative_to(plugin_dir)}: {issue}")
    allow_warnings, allow_errors = _scan_allowlist(plugin_dir, manifest)
    warnings += allow_warnings
    errors += allow_errors

    for warning in warnings:
        print(f"  ! {plugin_dir}: {warning}")
    if errors:
        print(f"[FAIL] {plugin_dir} — 发现 {len(errors)} 个问题:")
        for problem in errors:
            print(f"  - {problem}")
    else:
        print(f"[OK] {plugin_dir} — 未发现问题（{len(warnings)} 条警告）")
    return len(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scan_plugin",
        description="发布前安全扫描（生态工具，自包含）",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="扫描一个或多个插件目录")
    scan.add_argument("plugin_dirs", nargs="+", help="插件目录路径")
    scan.add_argument(
        "--manifest", action="append", default=[], help="插件清单 YAML 路径（与目录一一对应或只传一个）"
    )
    scan.add_argument("--json", action="store_true", help="JSON 输出")
    scan.add_argument("--entropy-threshold", type=float, default=DEFAULT_ENTROPY_THRESHOLD)
    args = parser.parse_args(argv)

    manifests = args.manifest or []
    results: dict[str, int] = {}
    total = 0
    for index, dir_arg in enumerate(args.plugin_dirs):
        manifest = Path(manifests[index]) if index < len(manifests) else None
        count = scan_plugin_dir(
            Path(dir_arg),
            manifest=manifest,
            entropy_threshold=args.entropy_threshold,
        )
        results[dir_arg] = count
        total += count
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n扫描完成: {len(results)} 个目录, {total} 个问题")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
