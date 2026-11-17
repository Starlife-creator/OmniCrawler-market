"""CLI 端到端：`omnicrawler pdf run` 走完整命令行路径产出五表。

## 为什么需要这条（与 tests/e2e 的区别）

已有 `tests/e2e/test_full_pipeline.py` 走的是 **Python API**
（`plugin.run_operation(...)`）。那条测的是插件内部逻辑。

本文件走**真实命令行**，覆盖 API 测不到的几段：

1. `argparse` 解析与参数转发（`--config` 位置、子命令分发）；
2. **子进程里插件能否加载**——这一段曾独立出过问题：
   加签名闸门后 8 条测试变红，根因正是"`monkeypatch.setenv` 只影响当前
   进程，子进程继承不到"；
3. 退出码与 stdout 形态（用户/脚本实际依赖的东西）；
4. 真实落盘产物（含 xlsx、text 目录、summary.json）。

## 判据

退出码 0、results.csv 存在且**内容正确**、SQLite 已建。
只看"命令没报错"不够——那次 `run_processing` 缺陷的表现正是
"命令成功、表齐全、但一行数据都没有"。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("reportlab", reason="需要 reportlab 生成真实 PDF")

#: 插件根（plugin.py 所在目录）：本文件在 <root>/tests/e2e/ 下。
_PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def _find_host() -> Path | None:
    """向上找同级 OmniCrawler 仓。

    不用固定层数：插件在 market 仓里的深度可能变（submissions/plugins/<fp>/<id>
    与 plugins/<fp>/<id>/versions/<ver> 层数不同），写死 parents[N] 会在
    搬目录后静默 skip——那等于守卫失效却不报警。
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "OmniCrawler"
        if (candidate / "src" / "omnicrawler").is_dir():
            return candidate
    return None


_HOST = _find_host()
if _HOST is None:
    pytest.skip("找不到宿主 OmniCrawler 仓", allow_module_level=True)


def _build_pdf(path: Path, invoice: str) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    canvas = Canvas(str(path), pagesize=A4)
    width, height = A4
    canvas.setFont("Helvetica", 14)
    canvas.drawString(72, height - 100, f"Invoice No: {invoice}")
    canvas.drawString(72, height - 130, "Amount: 9,876.54 yuan")
    canvas.showPage()
    canvas.save()


def test_cli_run_produces_five_tables_with_correct_content(tmp_path: Path) -> None:
    """`omnicrawler pdf run` 必须真的抽出字段并产出交付物。"""
    inbox = tmp_path / "in"
    inbox.mkdir()
    _build_pdf(inbox / "invoice.pdf", "HT-2026-0002")

    config = tmp_path / "project.yaml"
    config.write_text(
        f"""project_name: cli-e2e
input_dir: {inbox}
work_dir: {tmp_path / "work"}
output_dir: {tmp_path / "out"}
database: {tmp_path / "work" / "state.sqlite3"}
ocr: {{backend: none}}
fields:
  - name: invoice_no
    label: 发票号
    type: text
    required: true
    aliases: [发票号, "Invoice No"]
    patterns: ['Invoice No\\s*[:：]\\s*(?P<value>[A-Z]{{2}}-\\d{{4}}-\\d{{4}})']
""",
        encoding="utf-8",
    )

    localappdata = tmp_path / "localappdata"
    localappdata.mkdir()
    env = {
        **os.environ,
        "PYTHONPATH": str(_HOST / "src"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        # 插件未签名：声明开发模式（生产仍 strict 拒载）
        "OMNICRAWL_PLUGIN_SIGNATURE_POLICY": "developer",
        "OMNICRAWL_PDF_PLUGIN_DIR": str(_PLUGIN_ROOT),
        # 数据目录落在临时区，避免写用户目录被沙箱拒绝
        "LOCALAPPDATA": str(localappdata),
    }

    # 本沙箱禁命名管道，不用 capture_output，改重定向到文件
    log = tmp_path / "cli.log"
    with log.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(
            [
                sys.executable, "-m", "omnicrawler", "pdf",
                "--config", str(config), "run",
            ],
            stdout=handle,
            stderr=subprocess.STDOUT,
            cwd=str(_HOST),
            env=env,
            timeout=300,
            check=False,
        )
    output = log.read_text(encoding="utf-8", errors="replace")

    assert completed.returncode == 0, f"CLI 退出码 {completed.returncode}：\n{output[-1500:]}"

    out = tmp_path / "out"
    assert out.is_dir(), f"没有输出目录：{output[-800:]}"

    results = out / "results.csv"
    assert results.is_file(), f"缺 results.csv，实际产出：{sorted(p.name for p in out.iterdir())}"

    content = results.read_text(encoding="utf-8-sig")
    assert "HT-2026-0002" in content, (
        "results.csv 里没有抽到发票号——命令成功、表齐全但内容为空，"
        f"正是当年 `run_processing` 缺陷的症状。前 400 字：\n{content[:400]}"
    )

    assert (tmp_path / "work" / "state.sqlite3").is_file(), "没建 SQLite 数据库"


def test_cli_reports_error_for_missing_config(tmp_path: Path) -> None:
    """配置不存在时必须是**可读错误 + 非零退出码**，不是栈。"""
    env = {
        **os.environ,
        "PYTHONPATH": str(_HOST / "src"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "OMNICRAWL_PLUGIN_SIGNATURE_POLICY": "developer",
        "OMNICRAWL_PDF_PLUGIN_DIR": str(_PLUGIN_ROOT),
        "LOCALAPPDATA": str(tmp_path / "localappdata"),
    }
    (tmp_path / "localappdata").mkdir()

    log = tmp_path / "err.log"
    with log.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(
            [
                sys.executable, "-m", "omnicrawler", "pdf",
                "--config", str(tmp_path / "nope.yaml"), "status",
            ],
            stdout=handle,
            stderr=subprocess.STDOUT,
            cwd=str(_HOST),
            env=env,
            timeout=180,
            check=False,
        )
    output = log.read_text(encoding="utf-8", errors="replace")

    assert completed.returncode != 0, f"缺配置却退出 0：\n{output[-600:]}"
    assert "Traceback" not in output or "配置" in output, (
        f"只给了栈没给可读原因：\n{output[-800:]}"
    )
