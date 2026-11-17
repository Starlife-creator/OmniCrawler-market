"""插件测试的公共装配。

**为什么插件仓需要自己的 conftest**：这些测试原本在宿主仓里跑，
依赖宿主的 `tests/conftest.py`（sys.path 装配、fixtures）。
迁到插件仓后必须自带，否则 `import omnicrawler_pdf` 找不到包。

装配两件事：

1. 把**插件根目录**加进 `sys.path`——`omnicrawler_pdf` 是插件内的包；
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

    # 插件位于 <repo>/OmniCrawler-market/plugins/pdf-workbench，
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
