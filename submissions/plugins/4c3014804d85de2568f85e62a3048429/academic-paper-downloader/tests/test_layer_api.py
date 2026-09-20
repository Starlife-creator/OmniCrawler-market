"""Layer 2: API 探测测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _try_api_probe


class TestLayerApi:
    def test_invalid_doi(self):
        result = _try_api_probe("99.9999/nonexistent", {})
        assert result is None