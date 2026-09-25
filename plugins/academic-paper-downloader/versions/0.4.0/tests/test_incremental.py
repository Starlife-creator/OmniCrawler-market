"""增量导入测试。"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin import _parse_input_file


class TestIncrementalImport:
    def test_nonexistent_file(self):
        assert _parse_input_file("nonexistent.xlsx") == []

    def test_tsv(self):
        import tempfile
        content = "DOI\tTitle\n10.1039/test\tTest Paper\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            result = _parse_input_file(f.name)
            assert len(result) == 1
            assert result[0]["DOI"] == "10.1039/test"

    def test_csv(self):
        import tempfile
        content = "DOI,Title\n10.1039/test,Test Paper\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            result = _parse_input_file(f.name)
            assert len(result) == 1
            assert result[0]["DOI"] == "10.1039/test"

    def test_json(self):
        import tempfile, json
        data = [{"DOI": "10.1039/test", "Article Title": "Test"}]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            result = _parse_input_file(f.name)
            assert len(result) == 1
            assert result[0]["DOI"] == "10.1039/test"

    def test_ris(self):
        import tempfile
        content = """TY  - JOUR
TI  - Test Paper
DO  - 10.1039/test
PY  - 2025
ER  -
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ris", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            result = _parse_input_file(f.name)
            assert len(result) == 1
            assert result[0]["DOI"] == "10.1039/test"
            assert result[0]["Article Title"] == "Test Paper"

    def test_bibtex(self):
        import tempfile
        content = """@article{test2025,
  title={Test Paper},
  doi={10.1039/test},
  year={2025}
}
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".bib", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            result = _parse_input_file(f.name)
            assert len(result) == 1
            assert result[0]["DOI"] == "10.1039/test"
            assert result[0]["Article Title"] == "Test Paper"
