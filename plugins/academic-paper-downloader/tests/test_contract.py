"""Academic Paper Downloader 契约测试。"""

import pytest
from pathlib import Path

pytest.importorskip("omnicrawler")

from omnicrawler.plugins.plugin_contract_suite import Contract2Suite


class TestContract(Contract2Suite):
    """标准契约 2 验收测试。"""

    pytestmark = pytest.mark.plugin_contract

    @pytest.fixture(scope="class")
    def contract_plugin_dir(self):
        return Path(__file__).resolve().parents[1]