"""DOI 解析与出版商路由测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _extract_doi, _resolve_publisher, _extract_pii


class TestExtractDoi:
    def test_doi_field(self):
        row = {"DOI": "10.1016/j.jechem.2025.03.052"}
        assert _extract_doi(row) == "10.1016/j.jechem.2025.03.052"

    def test_doi_link_field(self):
        row = {"DOI Link": "http://dx.doi.org/10.1021/acs.jctc.4c01520"}
        assert _extract_doi(row) == "10.1021/acs.jctc.4c01520"

    def test_doi_in_url(self):
        row = {"SomeUrl": "https://example.com/10.1039/d2cp02827a"}
        assert _extract_doi(row) == "10.1039/d2cp02827a"

    def test_no_doi(self):
        row = {"Title": "Some Paper"}
        assert _extract_doi(row) is None


class TestResolvePublisher:
    def test_elsevier(self):
        assert _resolve_publisher("10.1016/j.jechem.2025.03.052") == "elsevier"
    def test_springer(self):
        assert _resolve_publisher("10.1007/s00894-025-06304-z") == "springer"
    def test_acs(self):
        assert _resolve_publisher("10.1021/acs.jctc.4c01520") == "acs"
    def test_aip(self):
        assert _resolve_publisher("10.1063/5.0020543") == "aip"
    def test_rsc(self):
        assert _resolve_publisher("10.1039/d2cp02827a") == "rsc"
    def test_wiley(self):
        assert _resolve_publisher("10.1002/advs.202513098") == "wiley"
    def test_aps(self):
        assert _resolve_publisher("10.1103/PhysRevResearch.7.013289") == "aps"
    def test_mdpi(self):
        assert _resolve_publisher("10.3390/pharmaceutics14091972") == "mdpi"
    def test_unknown(self):
        assert _resolve_publisher("99.9999/test") is None


class TestExtractPii:
    def test_valid_elsevier_doi(self):
        assert _extract_pii("10.1016/j.jechem.2025.03.052") == "j.jechem.2025.03.052"
    def test_non_elsevier_doi(self):
        assert _extract_pii("10.1021/acs.jctc.4c01520") == ""