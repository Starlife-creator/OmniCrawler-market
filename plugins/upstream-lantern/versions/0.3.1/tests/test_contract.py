from pathlib import Path

import pytest

from omnicrawler.plugins.plugin_contract_suite import Contract2Suite


class TestUpstreamLanternContract(Contract2Suite):
    @pytest.fixture(scope="class")
    @staticmethod
    def contract_plugin_dir():
        return Path(__file__).resolve().parents[1]
