import itertools
import os
import shutil as _shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Mirror the subprocess worker's package-root import path for bundled helpers.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Windows 沙箱环境：系统临时目录（以及 pytest --basetemp）可能返回 WinError 5。
# 为让 tmp_path / TemporaryDirectory 可用，统一把临时目录重定向到仓库内 .tmp/。
_REPO_ROOT = Path(__file__).resolve().parents[1]
_TMP_ROOT = _REPO_ROOT / ".tmp"
_TMP_ROOT.mkdir(exist_ok=True)
os.environ.setdefault("TMPDIR", str(_TMP_ROOT))
os.environ.setdefault("TMP", str(_TMP_ROOT))
os.environ.setdefault("TEMP", str(_TMP_ROOT))

_COUNTER = itertools.count()


@pytest.fixture
def tmp_path(monkeypatch):
    """沙箱可靠的 tmp_path：重定向到仓库内 .tmp/，避免 WinError 5。

    不能用 tempfile.mkdtemp()——它创建的子目录权限收紧（沙箱内不可再建子目录）。
    改用普通 mkdir，保持与父目录相同的继承权限。
    """
    monkeypatch.setenv("TMP", str(_TMP_ROOT))
    monkeypatch.setenv("TEMP", str(_TMP_ROOT))
    monkeypatch.setenv("TMPDIR", str(_TMP_ROOT))
    for _ in range(100):
        p = _TMP_ROOT / f"apd-test-{next(_COUNTER)}-{os.getpid()}"
        try:
            p.mkdir()
            break
        except FileExistsError:
            continue
    else:  # pragma: no cover
        raise RuntimeError("无法分配测试临时目录")
    yield p
    _shutil.rmtree(p, ignore_errors=True)
