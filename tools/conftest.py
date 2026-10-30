"""pytest 引导：把 ``tools/`` 加入 sys.path，使 ``catalog_lib`` 包可直接导入。

市场仓历史上只有 ``tools/check_*.py`` 自包含脚本（P1-4：工具链零单测）。本目录
是补建的 pytest 回归层；CI 在 ``validate.yml`` 中执行 ``pytest tools/tests``。
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
