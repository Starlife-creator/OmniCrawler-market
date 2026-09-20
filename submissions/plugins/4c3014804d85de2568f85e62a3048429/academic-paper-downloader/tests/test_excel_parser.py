"""Excel 解析测试。"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _parse_input_file


class TestExcelParser:
    def test_parse_nonexistent_file(self):
        result = _parse_input_file("nonexistent.xlsx")
        assert result == []

    def test_parse_tsv(self):
        content = "DOI\tArticle Title\tAuthors\n10.1039/test\tTest Paper\tAuthor A\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            result = _parse_input_file(f.name)
            assert len(result) == 1
            assert result[0]["DOI"] == "10.1039/test"
            assert result[0]["Article Title"] == "Test Paper"