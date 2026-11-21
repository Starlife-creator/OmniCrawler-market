"""组件「能跑」闸门：真实装配 + 照 `smoke` 执行 + 核对 `expect`。

## 这个脚本解决什么

`validate.yml` 只验结构与签名，**从不 import** 任何组件 —— 于是市场可以发布
一个永远跑不起来的配方。`ocr-paddle` 就长期处在「能发布、跑不起来」的状态。

本脚本在 CI 里对每个组件：

1. `install-recipe --download`（真从上游拉字节）；
2. 若 `smoke.skip_run` 为真 ⇒ 装好即算通过（纯数据组件）；
3. 否则 `run --component-dir ... --payload ...`，退出码 0 **还不够** ——
   必须核对组件自己声明的 `smoke.expect` 里的键存在且为真。

## 为什么判据读 `smoke` 而不是硬编码

组件自己说「我怎么算能跑」（`recipe.json` 的 `smoke`）。本脚本只当执行器，
新增组件**不需要改这里**。

## 退出码

`0` 全部通过 · `1` 有组件失败 · `2` 输入不可读
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class VerifyReport:
    """逐个组件的验证结果。"""

    installed: list[str] = field(default_factory=list)
    ran_ok: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failures: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        parts = [
            f"装上 {len(self.installed)} 个",
            f"跑通 {len(self.ran_ok)} 个",
            f"失败 {len(self.failures)} 个",
        ]
        if self.skipped:
            parts.append(f"跳过 {len(self.skipped)} 个")
        return "，".join(parts)


def _tail(text: str, limit: int = 600) -> str:
    """取输出末尾作为详情（滤掉带模块名的日志行）。"""
    lines = [
        line
        for line in (text or "").strip().splitlines()
        if line.strip()
        and not any(
            marker in line.lower()
            for marker in (" info omnicrawler", " warning omnicrawler", " debug omnicrawler")
        )
    ]
    cleaned = "\n".join(lines).strip()
    return cleaned[-limit:] if len(cleaned) > limit else cleaned


def _run(command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
        timeout=timeout,
        check=False,
    )


def _installed_dir(output: str) -> Path | None:
    """从 `install-recipe` 的输出里取组件目录（找 `安装到：` 行）。"""
    for line in (output or "").splitlines():
        stripped = line.strip()
        for prefix in ("安装到：", "安装到:"):
            if stripped.startswith(prefix):
                candidate = stripped[len(prefix) :].strip()
                if candidate and candidate != "?":
                    return Path(candidate)
    return None


def _verify_expect(expect: list[str], stdout: str) -> list[str]:
    """核对组件输出的 JSON 是否满足 `expect`。"""
    text = (stdout or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return [f"组件输出不是 JSON：{text[:200]!r}"]
    try:
        result = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        return [f"组件输出不是合法 JSON：{exc}"]
    if not isinstance(result, dict):
        return [f"组件输出不是对象：{type(result).__name__}"]
    if result.get("ok") is False:
        stage = result.get("stage") or "worker"
        error = result.get("error") or "未提供错误信息"
        return [f"[{stage}] {error}"]
    problems: list[str] = []
    for key in expect:
        if key not in result:
            problems.append(f"结果缺少期望的键：{key}")
        elif not result[key]:
            problems.append(f"期望的键值为假：{key}={result[key]!r}")
    return problems


def _smoke_of(recipe: dict[str, Any]) -> dict[str, Any]:
    """取组件的 smoke 声明（缺省按 data 处理）。"""
    smoke = recipe.get("smoke")
    if isinstance(smoke, dict):
        return smoke
    kind = str(recipe.get("kind") or "wheel-pack").strip().lower()
    return {"skip_run": kind == "data"}


def verify_all(root: Path) -> VerifyReport:
    """逐个组件验证。"""
    report = VerifyReport()
    # 组件按分类子目录组织：`components/<分类>/<id>/recipe.json`。
    # 一层 glob 会扫到 0 个 —— 而报错文案「未找到任何组件配方」看起来像
    # 目录不存在，实际是扫描深度不够（真实 CI 踩到，8 个组件被报成 0 个）。
    recipes = sorted(root.rglob("recipe.json"))
    if not recipes:
        report.failures.append(("*", "扫描", f"未找到任何组件配方：{root}"))
        return report

    executable = shutil.which("omnicrawler") or "omnicrawler"
    work = Path(tempfile.mkdtemp(prefix="component-verify-"))
    try:
        for recipe_path in recipes:
            cid = recipe_path.parent.name
            try:
                recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                report.failures.append((cid, "读取", f"配方无法解析：{exc}"))
                continue
            smoke = _smoke_of(recipe)

            # **内置组件（source: builtin）在 CI 上无法验证**：
            # 它的字节随主程序发布，本工作流没有装机包，必然找不到。
            # 这不是失败 —— 强行判红会让「内置物跟主仓走」的组件永远
            # 卡住市场闸门。如实记为「跳过」并说明原因。
            artifacts = recipe.get("artifacts") or []
            if artifacts and all(
                str(a.get("source") or "remote").lower() == "builtin"
                for a in artifacts
            ):
                report.skipped.append(
                    (cid, "内置组件：字节随主程序发布，市场 CI 无装机包可验")
                )
                continue

            installed = _run(
                [
                    executable,
                    "components",
                    "install-recipe",
                    "--recipe",
                    str(recipe_path.resolve()),
                    "--download",
                    "--component-root",
                    str(work / "components"),
                ],
                root.resolve().parent,
                timeout=1800,
            )
            if installed.returncode != 0:
                detail = _tail(installed.stderr) or _tail(installed.stdout) or (
                    f"退出码 {installed.returncode}"
                )
                report.failures.append((cid, "装配", detail))
                continue
            report.installed.append(cid)

            if smoke.get("skip_run"):
                report.ran_ok.append(f"{cid}（声明 skip_run，装好即完成）")
                continue

            component_dir = _installed_dir(installed.stdout) or _installed_dir(
                installed.stderr
            )
            if component_dir is None or not component_dir.is_dir():
                preview = _tail(f"{installed.stdout}{installed.stderr}", 300)
                report.failures.append(
                    (cid, "运行", f"装完后找不到组件目录；安装输出尾部：{preview}")
                )
                continue

            payload = smoke.get("payload") or {}
            timeout = float(smoke.get("timeout_seconds") or 300)
            ran = _run(
                [
                    executable,
                    "components",
                    "run",
                    "--component-dir",
                    str(component_dir),
                    "--payload",
                    json.dumps(payload, ensure_ascii=False),
                ],
                root.resolve().parent,
                timeout=timeout,
            )
            if ran.returncode != 0:
                detail = _tail(ran.stderr) or _tail(ran.stdout) or (
                    f"退出码 {ran.returncode}"
                )
                print(f"::group::{cid} 完整输出 (stdout)")
                print((ran.stdout or "")[:4000])
                print("::endgroup::")
                print(f"::group::{cid} 完整输出 (stderr)")
                print((ran.stderr or "")[:4000])
                print("::endgroup::")
                report.failures.append((cid, "运行", detail))
                continue

            expect = [str(x) for x in (smoke.get("expect") or [])]
            unmet = _verify_expect(expect, ran.stdout)
            if unmet:
                report.failures.append((cid, "核对", "；".join(unmet)))
                continue
            report.ran_ok.append(cid)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="组件能跑闸门")
    parser.add_argument("--root", type=Path, default=Path("components"))
    parser.add_argument("--report", type=Path, default=Path("components-runnable-report.json"))
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    root: Path = args.root
    if not root.is_dir():
        print(f"目录不存在：{root}", file=sys.stderr)
        return 2

    report = verify_all(root)
    print(f"组件能跑验证：{report.summary()}")
    for cid in report.installed:
        print(f"  ✓ 已装 {cid}")
    for cid, why in report.skipped:
        print(f"  - 跳过 {cid}：{why}")
    for cid in report.ran_ok:
        print(f"  ✓ 跑通 {cid}")
    for cid, stage, why in report.failures:
        print(f"  ✗ {cid} 在「{stage}」失败：{why}", file=sys.stderr)

    args.report.write_text(
        json.dumps(
            {
                "ok": report.ok,
                "installed": report.installed,
                "ran_ok": report.ran_ok,
                "skipped": report.skipped,
                "failures": report.failures,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
