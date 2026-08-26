"""catalog_lib —— generate_catalog 的分域实现包（FINAL 长期债 #3）。

拆分自单文件 tools/generate_catalog.py（936 行）；入口脚本仍为
tools/generate_catalog.py（薄壳 re-export），对外行为零变化。
"""
from .authors import *
from .build import *
from .cli import *
from .common import *
from .rules import *
from .schema import *
from .signing import *
from .tombstones import *
