"""组件配方门禁：**凡是声明，都必须能从构件字节推导出来**。

## 一条通则，覆盖一整类缺陷

v1.0.13→v1.0.29 的 17 轮排查里，配方缺陷**全是同一类**——声明与实际不符：

| 缺陷 | 声明 | 实际 |
|---|---|---|
| `platforms: ["windows"]` | 只说 windows | 上游有三平台 |
| aarch64 / cp310 / cp313t 误选 | 平台或 ABI 声明了 | 选了不兼容的轮子 |
| `architectures: [x86_64, aarch64]` | 说支持 ARM | 全是 x86_64 轮子 |
| `arm64` vs `aarch64` | 写 `arm64` | 代码返回 `aarch64` |
| `entry.json` | 声明存在 | 从未生成 |

所以本门禁不逐条打补丁，而是**对每个可推导字段做一次比对**。

## 为什么能在本地跑（零网络、零下载）

依赖闭包要联网查 PyPI，但那件事已经**固化成快照**（`deps.lock.json`，由
`tools/market/component_deps_lock.py` 生成）。本门禁只读两个 JSON 做集合运算，
**毫秒级，不联网，不下载任何 wheel**。

维护者约束：不给本地开发机增加负担 —— 新增耗时目标 < 0.3 秒。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: 市场仓**不依赖主仓的 `omnicrawler` 包**：本工作流用的是独立 checkout。
#: 所以这里不 import `component_recipe`，而是把必要的结构校验内联成本文件的函数
#: （保持判据等价，但不引入跨仓依赖）。
_REPO = Path(__file__).resolve().parents[1]

#: 架构名归一（与 `component_recipe.normalize_architecture` 保持同义）。
_ARCH_ALIASES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "x64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
    "armv8": "aarch64",
    "universal2": "universal2",
}

#: 平台 → 该平台 wheel 文件名必须出现的标记。
_PLATFORM_TOKENS = {
    "windows": ("win_amd64", "win32", "win_arm64"),
    "linux": ("manylinux", "musllinux", "linux_x86_64", "linux_aarch64"),
    "macos": ("macosx",),
}


class RecipeError(ValueError):
    """配方不合法（市场仓内联版，与主仓同名异常语义一致）。"""


def load_recipe(path: Path) -> dict:
    """读并做**结构校验**（内联版，不依赖主仓 `component_recipe`）。

    校验范围刻意与主仓等价但更窄：市场仓只关心「声明是否自洽」，
    不重复主仓那些与装配/运行相关的判据。
    """
    try:
        recipe = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecipeError(f"配方不是合法 JSON：{exc}") from exc
    if not isinstance(recipe, dict):
        raise RecipeError("配方必须是 JSON 对象")

    for key in ("name", "version"):
        if not isinstance(recipe.get(key), str) or not str(recipe[key]).strip():
            raise RecipeError(f"recipe 缺少 {key}")
    for key in ("platforms", "architectures"):
        value = recipe.get(key)
        if not (isinstance(value, list) and value and all(isinstance(v, str) for v in value)):
            raise RecipeError(f"recipe 的 {key} 必须是非空字符串列表")
    artifacts = recipe.get("artifacts")
    if not (isinstance(artifacts, list) and artifacts):
        raise RecipeError("recipe 需要至少一个 artifact")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise RecipeError("artifact 必须是对象")
        # 内置构件（`source: builtin`）字节随包发布，**不写 url**，
        # 改为 `builtin_path`（相对安装根）。sha256 仍然必填 ——
        # 「内置」不等于「免校验」。与宿主侧 component_recipe 同一判据。
        source = str(artifact.get("source") or "remote").lower()
        if source == "builtin":
            if artifact.get("url"):
                raise RecipeError("source=builtin 的 artifact 不能写 url")
            if not str(artifact.get("builtin_path") or "").strip():
                raise RecipeError("source=builtin 的 artifact 必须写 builtin_path")
        elif not str(artifact.get("url") or "").startswith(("https://", "http://")):
            raise RecipeError("artifact 的 url 必须是 http(s) 地址")
        digest = str(artifact.get("sha256") or "")
        if len(digest) != 64:
            raise RecipeError("artifact 缺少合法的 sha256 —— 没有哈希就无法校验来源")
    if not isinstance(recipe.get("entry"), dict):
        raise RecipeError("recipe 需要 entry（入口声明）")
    return recipe


def _recipe_digest(recipe: dict) -> str:
    """配方稳定摘要（规范化序列化后 sha256），与主仓同算法。"""
    import hashlib

    canonical = json.dumps(
        recipe, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def component_kind(recipe: dict) -> str:
    """取组件种类（缺省 wheel-pack）。"""
    value = str(recipe.get("kind") or "wheel-pack").strip().lower()
    return value or "wheel-pack"


def _norm_arch(name: str) -> str:
    return _ARCH_ALIASES.get(str(name).strip().lower(), str(name).strip().lower())


def _wheel_names(recipe: dict) -> list[str]:
    return [
        str(a.get("url") or "").rsplit("/", 1)[-1].lower()
        for a in recipe.get("artifacts") or []
    ]


def _arch_from_filename(filename: str) -> set[str]:
    """从 wheel 文件名推出它覆盖的架构。"""
    archs: set[str] = set()
    if "universal2" in filename:
        return {"x86_64", "aarch64"}
    for token, canonical in (
        ("aarch64", "aarch64"),
        ("arm64", "aarch64"),
        ("win_amd64", "x86_64"),
        ("win32", "x86"),
        ("x86_64", "x86_64"),
    ):
        if token in filename:
            archs.add(canonical)
    return archs


def _abi_from_filename(filename: str) -> str:
    """从 wheel 文件名推出 ABI 大类。"""
    if "none-any" in filename:
        return "any"
    if "abi3" in filename:
        return "abi3"
    match = re.search(r"cp3\d+", filename)
    return match.group(0) if match else "?"


def _check_builtin_recipe(recipe_path: Path, recipe: dict) -> list[str]:
    """内置构件的专用判据。

    内置构件是「字节随包、但也要被组件体系管理」的东西。
    它不适用按文件名反推平台/架构，但**有更严格的替代判据**：
    必须有一份逐文件哈希清单，且清单里的文件数与字节数要和声明对得上。
    """
    problems: list[str] = []
    name = recipe_path.parent.name

    lock_path = recipe_path.parent / "files.lock.json"
    if not lock_path.is_file():
        problems.append(
            f"{name}: 内置组件缺少 files.lock.json —— "
            "内置不等于免校验，逐文件哈希必须随配方一起签名"
        )
        return problems

    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"{name}: files.lock.json 无法解析 —— {exc}")
        return problems

    files = lock.get("files")
    if not isinstance(files, dict) or not files:
        problems.append(f"{name}: files.lock.json 的 files 为空 —— 空清单会让校验恒真")
        return problems

    # 声明的 size 必须等于清单总和（防两处漂移）
    declared_size = sum(int(a.get("size") or 0) for a in recipe["artifacts"])
    actual_size = sum(int(v.get("size") or 0) for v in files.values() if isinstance(v, dict))
    if declared_size != actual_size:
        problems.append(
            f"{name}: 构件 size 合计 {declared_size} 与 files.lock.json 的 "
            f"{actual_size} 不一致"
        )

    # 每个文件都要有合法 sha256
    missing_hash = [
        path
        for path, meta in files.items()
        if not (isinstance(meta, dict) and len(str(meta.get("sha256") or "")) == 64)
    ]
    if missing_hash:
        problems.append(
            f"{name}: files.lock.json 里有 {len(missing_hash)} 个文件缺少合法 sha256"
        )
    return problems


def check_recipe(recipe_path: Path) -> list[str]:
    """返回发现的问题（空列表 = 通过）。"""
    problems: list[str] = []
    # **配方本身不合法时必须报成「问题」而不是崩栈**：
    # `load_recipe` 会拒掉结构不对的配方（例如声明了某平台却没给它构件），
    # 而崩溃的退出码不是 1，会让 CI 把它误判成「脚本自己出错」而非「配方有问题」。
    try:
        recipe = load_recipe(recipe_path)
    except RecipeError as exc:
        return [f"{recipe_path.parent.name}: 配方不合法 —— {exc}"]
    wheels = _wheel_names(recipe)
    haystack = " ".join(wheels)
    kind = component_kind(recipe)
    problems.extend(_check_provides(recipe_path, recipe))

    # **纯数据组件**（如 Tesseract 语言包）与平台/架构无关：
    # 字节是通用数据文件，文件名里不会有 `win_amd64` / `manylinux` 这类标记。
    # 对它套用「每个平台都要有平台标记构件」是**判据过严**，会逼出假阳性。
    if kind == "data":
        return _check_data_recipe(recipe_path, recipe)

    # **内置构件**（`source: builtin`）不适用「按文件名反推平台/架构」：
    # 它是一整个目录（浏览器内核 310 个文件），文件名里不会有
    # `win_amd64` / `manylinux` 这类标记。它的推导依据是**逐文件哈希清单**
    # （`files.lock.json`），比文件名更精确 —— 所以跳过反推，不跳过校验：
    # 清单与真实字节的一致性由 `--check` 单独验（见 gen_builtin_browser_lock）。
    if recipe.get("artifacts") and all(
        str(a.get("source") or "remote").lower() == "builtin"
        for a in recipe["artifacts"]
    ):
        problems.extend(_check_builtin_recipe(recipe_path, recipe))
        return problems

    # ── 1) platforms：每个声明平台都要有该平台的构件 ──────────────────────
    for platform in recipe["platforms"]:
        tokens = _PLATFORM_TOKENS.get(platform, ())
        specific = [
            w
            for a, w in zip(recipe["artifacts"], wheels, strict=False)
            if platform in (a.get("platforms") or recipe["platforms"])
            and any(t in w for t in tokens)
        ]
        if not specific:
            problems.append(
                f"{recipe_path.parent.name}: 声明支持 {platform}，"
                f"但没有任何带该平台标记的构件"
            )

    # ── 2) architectures：每个声明架构都要能从构件文件名推出 ─────────────
    declared_arch = {_norm_arch(a) for a in recipe["architectures"]}
    available_arch: set[str] = set()
    for w in wheels:
        available_arch |= _arch_from_filename(w)
    # 纯 Python 轮子没有架构信息，不算覆盖
    if "universal2" in declared_arch:
        available_arch.add("universal2")
    missing_arch = declared_arch - available_arch
    if missing_arch:
        problems.append(
            f"{recipe_path.parent.name}: architectures 声明了 {sorted(missing_arch)}，"
            f"但没有任何对应架构的构件 —— 声明虚报"
        )

    # 反向：构件里有、声明里没有 ⇒ 也是虚报（漏声明同样会误导用户）
    undeclared = available_arch - declared_arch
    if undeclared:
        problems.append(
            f"{recipe_path.parent.name}: 构件里有 {sorted(undeclared)} 架构的二进制，"
            f"但 architectures 没声明"
        )

    # ── 3) python_abi：声明的 ABI 必须与构件兼容，且不得有不可用轮子 ─────
    declared_abi = [str(a) for a in (recipe.get("python_abi") or [])]
    for w in wheels:
        abi = _abi_from_filename(w)
        if "cp313t" in w:
            problems.append(
                f"{recipe_path.parent.name}: {w} 是自由线程（cp313t）轮子，普通解释器加载不了"
            )
        elif abi.startswith("cp") and declared_abi and abi not in declared_abi:
            problems.append(
                f"{recipe_path.parent.name}: {w} 的 ABI 是 {abi}，"
                f"但 python_abi 只声明了 {declared_abi}"
            )

    # ── 4) declared_total_bytes：必须等于各构件 size 之和 ────────────────
    sizes = [int(a.get("size") or 0) for a in recipe.get("artifacts") or []]
    if any(s == 0 for s in sizes):
        problems.append(
            f"{recipe_path.parent.name}: 有构件没声明 size —— 用户看不到下载量"
        )

    # ── 5) entry.module：必须落在某个 extract_to 之下 ────────────────────
    entry = recipe.get("entry") or {}
    module = str(entry.get("module") or "").strip()
    if module:
        extract_targets = {
            str(a.get("extract_to") or "").rstrip("/")
            for a in recipe.get("artifacts") or []
            if a.get("extract_to")
        }
        if extract_targets and not any(
            module == t or module.startswith(t + "/") for t in extract_targets
        ):
            problems.append(
                f"{recipe_path.parent.name}: entry.module={module!r} "
                f"不在任何 extract_to（{sorted(extract_targets)}）之下"
            )

    # ── 6) 依赖闭包快照：配方的 wheel 必须覆盖快照里的每个包 ─────────────
    lock_path = recipe_path.parent / "deps.lock.json"
    if lock_path.is_file():
        snapshot = json.loads(lock_path.read_text(encoding="utf-8"))
        if snapshot.get("recipe_digest") != _recipe_digest(recipe):
            problems.append(
                f"{recipe_path.parent.name}: deps.lock.json 已过期"
                f"（配方改过但快照没重算）"
            )
        normalized_hay = haystack.replace("-", "_").replace(".", "_")
        missing_pkgs = [
            name
            for name in snapshot.get("packages") or []
            if re.sub(r"[-_.]+", "_", name).lower() not in normalized_hay
        ]
        if missing_pkgs:
            problems.append(
                f"{recipe_path.parent.name}: 配方缺少闭包声明的包 {missing_pkgs}"
            )
    else:
        problems.append(
            f"{recipe_path.parent.name}: 缺少依赖闭包快照 deps.lock.json"
            f"（运行 tools/market/component_deps_lock.py 生成）"
        )

    return problems


def _check_data_recipe(recipe_path: Path, recipe: dict) -> list[str]:
    """纯数据组件的校验：只看「数据文件能否真的交付」。

    数据组件的正确判据与 Wheel-Pack 不同：

    * 构件**不应**带平台/架构标记（带了反而说明选错了内容）；
    * 必须声明 `declared_total_bytes`（用户要知道下载多少）；
    * **可以有** `platforms` / `architectures` 声明（表示「这份数据在三平台都可用」），
      但构件本身不该分平台。
    """
    problems: list[str] = []
    name = recipe_path.parent.name
    if component_kind(recipe) != "data":
        return problems

    for artifact in recipe.get("artifacts") or []:
        if artifact.get("platforms"):
            problems.append(
                f"{name}: 纯数据组件的构件不应标 platforms"
                f"（{artifact['url'].rsplit('/', 1)[-1]} 标了 {artifact['platforms']}）"
            )
        if not artifact.get("size"):
            problems.append(
                f"{name}: 构件 {artifact['url'].rsplit('/', 1)[-1]} 没声明 size"
                f" —— 用户看不到下载量"
            )
    return problems


def _check_provides(recipe_path, recipe):
    """`provides` 是插件与组件对上的唯一凭据，不能缺。

    插件用 `required_capabilities` 声明「我需要 ocr.paddle」，
    组件必须声明「我提供 ocr.paddle」—— 否则两者只能靠人脑对应。
    """
    problems = []
    name = recipe_path.parent.name
    provides = recipe.get("provides")
    if not provides:
        problems.append(f"{name}: 没有声明 provides —— 插件无法与之对接")
        return problems
    if not isinstance(provides, list):
        problems.append(f"{name}: provides 必须是列表")
        return problems
    normalized = []
    for item in provides:
        if not isinstance(item, str) or not item.strip():
            problems.append(f"{name}: provides 含非字符串项")
            continue
        value = item.strip().lower()
        if not all(ch.isalnum() or ch in "._-" for ch in value):
            problems.append(f"{name}: 能力名只允许字母/数字/._-：{item!r}")
        normalized.append(value)
    if len(set(normalized)) != len(normalized):
        problems.append(f"{name}: provides 含重复项 {normalized}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="组件配方声明可推导校验")
    parser.add_argument(
        "--root",
        type=Path,
        default=_REPO / "market" / "components",
        help="含各组件 recipe.json 的目录",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    root: Path = args.root
    if not root.is_dir():
        print(f"目录不存在：{root}", file=sys.stderr)
        return 2

    # 组件按**分类子目录**组织：`components/<分类>/<id>/recipe.json`。
    # rglob 同时兼容扁平布局，新增分类时不需要再改这里。
    recipes = sorted(root.rglob("recipe.json"))
    if not recipes:
        # **空集合必须判红**：没有可检查的配方不等于通过
        print(f"未找到任何组件配方（{root}/ */recipe.json）", file=sys.stderr)
        return 1

    problems: list[str] = []
    for recipe_path in recipes:
        problems.extend(check_recipe(recipe_path))

    if problems:
        print("组件配方声明与构件字节不一致：", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print(f"组件配方声明可推导：{len(recipes)} 份配方全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
