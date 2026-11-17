"""插件测试的公共装配。

**为什么插件仓需要自己的 conftest**：这些测试原本在宿主仓里跑，
依赖宿主的 `tests/conftest.py`（sys.path 装配、fixtures）。
迁到插件仓后必须自带，否则 `import omnicrawler_docs` 找不到包。

装配两件事：

1. 把**插件根目录**加进 `sys.path`——`omnicrawler_docs` 是插件内的包；
2. 把**宿主 `src/`** 加进 `sys.path`——插件在 in_process 模式下会
   `import omnicrawler.*`（契约 1 允许），测试里也会用到宿主侧工具。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

#: 宿主 `src/` 的位置：优先环境变量，其次按常见布局推断。
_HOST_SRC_ENV = "OMNICRAWL_HOST_SRC"


def _host_src() -> Path | None:
    explicit = os.environ.get(_HOST_SRC_ENV, "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if (candidate / "omnicrawler").is_dir():
            return candidate

    # 插件位于 <repo>/OmniCrawler-market/plugins/document-workbench，
    # 宿主位于同级 <repo>/OmniCrawler/src。
    repo = PLUGIN_ROOT.parents[2]
    candidate = repo / "OmniCrawler" / "src"
    if (candidate / "omnicrawler").is_dir():
        return candidate
    return None


def pytest_configure(config) -> None:
    """把插件根与宿主 src 加入 sys.path（幂等）。"""
    for entry in (str(PLUGIN_ROOT),):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    host = _host_src()
    if host is not None and str(host) not in sys.path:
        sys.path.insert(0, str(host))


def pytest_sessionstart(session) -> None:
    """让宿主的插件探测能看见**本插件自己**。

    `document_facade._plugin_dir()` 默认查 cwd / 应用目录 / 配置根，
    而插件测试运行时这三处都指向宿主仓，不是插件仓——于是
    `document_capability()` 会误报"未安装"（实测：document_ir 三组
    测试因此红）。这里用官方提供的显式通道指过去。
    """
    os.environ.setdefault("OMNICRAWL_PDF_PLUGIN_DIR", str(PLUGIN_ROOT))

    # 必须用 `os.environ` 而不是 pytest 的 monkeypatch：
    # 本仓有若干测试会**起子进程**跑 `omnicrawler pdf …`（CLI 位置、
    # 转换生命周期等）。monkeypatch 只影响当前进程，子进程继承不到，
    # 于是子进程里插件被签名闸门拒绝（实测：8 条测试因此红）。
    #
    # 这里声明开发模式：本仓插件是未签名的源码目录，生产仍走 strict。
    # 差异**仅限验签**这一项；闸门本身仍会执行并调用 verify_plugin_trust。
    os.environ.setdefault("OMNICRAWL_PLUGIN_SIGNATURE_POLICY", "developer")

def pytest_configure(config) -> None:
    """把 pytest 的临时根移出插件目录。

    **为什么必须这么做**：本环境的 pytest 默认把 ``pytest-of-<user>/`` 建在
    **当前工作目录**（也就是插件根）下。而插件测试里有会写 ``.env`` 的用例，
    于是插件目录里出现 ``pytest-of-Lenovo/.../proj/.env``。

    ``sign_plugin.py`` / ``package_manifest._payload_files`` **不看 .gitignore**，
    它们扫磁盘实际文件，并把 ``.env`` 判为「疑似凭据」直接拒签
    （实测：creator_sign 因此连续两次失败）。

    所以从源头解决：把 basetemp 指到插件目录之外的系统临时区。
    """
    import tempfile

    # \	empfile.gettempdir()\ 在本环境返回的是**仓库根**（不是系统临时区），
    # 所以不能直接用它——否则 basetemp 仍落在仓库内。这里显式排除：
    # 只要它落在 PLUGIN_ROOT 之内，就改用环境变量或 \LOCALAPPDATA\Temp\。
    candidate = Path(tempfile.gettempdir()) / "omnicrawler-plugin-pytest"
    try:
        candidate.relative_to(PLUGIN_ROOT)
        inside_repo = True
    except ValueError:
        inside_repo = False

    if inside_repo:
        fallback = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or ""
        candidate = Path(fallback) / "omnicrawler-plugin-pytest" if fallback else candidate

    try:
        candidate.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(candidate)
    except OSError:
        # 不可写时退回默认（宁可留残留，也不要测试跑不起来）
        pass
