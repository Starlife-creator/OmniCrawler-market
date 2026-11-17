"""端到端：真实 PDF → 完整管线 → 五表产出（插件入口级验证）。

**为什么这个文件必须存在**

插件已有 465 个模块级测试（config / database / parser / ocr / exporter
各自的判据全绿），但它们**测不到串联层**。2026-11-17 的实测证明了代价：

`processor.process` 当时调的是 `run_processing`，而它只做
`ingest → parse → ocr → text_export`，**不含抽取阶段**。症状极其隐蔽：

```
processor.process 成功        ← 看起来正常
五表产出齐全                  ← 表都在
但 results.csv 只有表头        ← 一行数据都没有
```

用户拿到的是"跑成功了，但什么也没抽到"。

**本文件钉住的判据**

1. 真实 PDF（reportlab 生成，不依赖外部样本）能被解析出文字；
2. `processor.process` 真的抽出字段（不是空表）；
3. `exporter.export` 产出五表齐全；
4. **抽到的值正确**（`HT-2026-0001` 真的出现在 results.csv 里）；
5. `extraction_methods` 有实际方法（`rules`），而不是空字典。

第 4、5 条是关键：只看"文件存在"会漏掉上面那个缺陷——
表在、文件在，但内容是空的。

**依赖**：`reportlab`（生成 PDF）。缺失时跳过而不是失败——
它是可选依赖，不该让整个测试模块红掉。
"""

from __future__ import annotations

import importlib

import json
from pathlib import Path

import pytest

pytest.importorskip("reportlab", reason="端到端测试需要 reportlab 生成真实 PDF")


def _build_pdf(path: Path) -> None:
    """生成一份带可抽取文字的 PDF（原生文字层，无需 OCR）。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen.canvas import Canvas

    canvas = Canvas(str(path), pagesize=A4)
    width, height = A4
    canvas.setFont("Helvetica", 14)
    canvas.drawString(72, height - 100, "Invoice No: HT-2026-0001")
    canvas.drawString(72, height - 130, "Amount: 12,345.67 yuan")
    canvas.drawString(72, height - 160, "Customer: Example Trading Co")
    canvas.showPage()
    canvas.save()


def _project_config(workdir: Path) -> dict:
    inbox = workdir / "in"
    inbox.mkdir(parents=True, exist_ok=True)
    return {
        "project_name": "e2e",
        "input_dir": str(inbox),
        "work_dir": str(workdir / "work"),
        "output_dir": str(workdir / "out"),
        "database": str(workdir / "work" / "state.sqlite3"),
        # 用原生文字层，不走 OCR：测试不该依赖本机装了什么 OCR 引擎。
        "ocr": {"backend": "none"},
        "fields": [
            {
                "name": "invoice_no",
                "label": "发票号",
                "type": "text",
                "source": "content",
                "required": True,
                "aliases": ["发票号", "Invoice No"],
                "patterns": [r"Invoice No\s*[:：]\s*(?P<value>[A-Z]{2}-\d{4}-\d{4})"],
            },
            {
                "name": "amount",
                "label": "金额",
                "type": "amount",
                "source": "content",
                "target_unit": "元",
                "aliases": ["金额", "Amount"],
                "patterns": [r"Amount\s*[:：]?\s*(?P<value>[\d,，.]+\s*(?:亿元|万元|元))"],
            },
        ],
    }


def _run(operation: str, payload: dict) -> dict:
    """经插件自己的 `run_operation` 执行（与宿主调用走同一条路）。"""
    import plugin

    return plugin.run_operation(operation, payload)


def test_full_pipeline_extracts_real_fields(tmp_path: Path) -> None:
    """真实 PDF 走完整管线：能解析、能抽取、能导出，且内容正确。"""
    config = _project_config(tmp_path)
    _build_pdf(Path(config["input_dir"]) / "invoice.pdf")

    processed = _run("processor.process", {"config": config})
    assert processed.get("ok"), f"processor.process 失败: {processed.get('error')}"

    result = processed.get("result") or {}
    extract = result.get("extract") or {}

    # 判据 2：真的抽出了记录（不是 0）
    assert extract.get("records", 0) >= 1, (
        f"抽取到 0 条记录——这正是 `run_processing` 当入口时的症状"
        f"（它不含抽取阶段）。extract={extract}"
    )
    # 判据 5：抽取方法非空
    assert extract.get("extraction_methods"), (
        f"extraction_methods 为空，说明抽取实际没跑：extract={extract}"
    )

    exported = _run("exporter.export", {"config": config})
    assert exported.get("ok"), f"exporter.export 失败: {exported.get('error')}"

    files = (exported.get("summary") or {}).get("files") or {}

    # CSV 三表是**无条件必需**（不依赖任何第三方包）。
    for name in ("results_csv", "review_csv", "long_csv"):
        assert name in files, f"导出缺 {name}: files={sorted(files)}"
        assert Path(files[name]).is_file(), f"{name} 指向的文件不存在: {files[name]}"

    # xlsx 依赖 openpyxl，缺失时 exporter **故意降级**：CSV 照常产出、
    # 把 `excel` 键移除、并在 summary 里给出明确原因（不静默跳过）。
    # 所以这里按实际依赖判断，不能硬断言——否则装不上 openpyxl 的环境
    # 会把"设计好的降级"误报成缺陷。
    if importlib.util.find_spec("openpyxl") is not None:
        assert "excel" in files, f"openpyxl 可用但没导出 excel: files={sorted(files)}"
        assert Path(files["excel"]).is_file(), f"excel 指向的文件不存在: {files['excel']}"
    else:
        assert "excel" not in files, "缺少 openpyxl 时不应给出 excel 路径（那是坏路径）"

    # 判据 4：抽到的值正确（这是最关键的一条——文件在 ≠ 内容对）
    results = Path(files["results_csv"]).read_text(encoding="utf-8-sig")
    assert "HT-2026-0001" in results, (
        "results.csv 里没有抽到发票号——"
        f"表产出齐全但内容为空。results 前 400 字:\n{results[:400]}"
    )


def test_pdf_text_layer_is_readable(tmp_path: Path) -> None:
    """解析层必须真的读到文字（区分"PDF 没问题"与"抽取有问题"）。

    这条单独立一个测试：如果上一个测试失败，能立刻判断是解析层还是抽取层的问题。
    """
    config = _project_config(tmp_path)
    _build_pdf(Path(config["input_dir"]) / "invoice.pdf")

    processed = _run("processor.process", {"config": config})
    assert processed.get("ok")

    result = processed.get("result") or {}
    processing = result.get("processing") or {}
    parse = processing.get("parse") or result.get("parse") or {}
    assert parse.get("parsed", 0) >= 1, f"PDF 没被解析成功：parse={parse}"

    # 文字层产物里应出现原始内容
    text_dir = Path(config["output_dir"]) / "text"
    texts = list(text_dir.glob("*.txt")) if text_dir.is_dir() else []
    assert texts, f"没有生成文字层文件（目录 {text_dir}）"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in texts)
    assert "HT-2026-0001" in combined, (
        f"文字层里没有原始内容，说明解析读空。实际内容:\n{combined[:400]}"
    )


def test_selfcheck_reports_no_missing_required() -> None:
    """插件自检的必需依赖必须齐备（安装后立刻可用）。"""
    import plugin

    report = plugin.selfcheck()
    assert report["ok"], f"插件自检失败：{json.dumps(report, ensure_ascii=False)[:500]}"
    assert report["required_missing"] == []


def test_missing_openpyxl_degrades_to_csv_with_clear_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缺 openpyxl 时必须降级：CSV 照常产出 + 明确原因，且不给 excel 坏路径。

    这是用户会真的遇到的场景（没装 openpyxl）。设计上 exporter 故意降级
    而不是整个失败——但"降级"必须**说出来**，不能静默少一个文件让用户去猜。

    判据：
    1. 三张 CSV 仍然产出；
    2. `files` 里**没有** `excel` 键（给键就是坏路径）；
    3. summary 里有可操作的原因（含 pip install 提示）。
    """
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "openpyxl" or name.startswith("openpyxl."):
            raise ImportError("模拟 openpyxl 缺失")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    from omnicrawler_docs.pdfx.database import Database
    from omnicrawler_docs.pdfx.exporter import export_stage
    from omnicrawler_docs.pdfx.config import load_config

    workdir = tmp_path
    config_path = workdir / "p.yaml"
    config_path.write_text(
        f"""project_name: degrade
input_dir: {workdir / 'in'}
work_dir: {workdir / 'w'}
output_dir: {workdir / 'out'}
database: {workdir / 'w' / 's.sqlite3'}
ocr: {{backend: none}}
fields:
  - name: a
    label: A
    type: text
    patterns: ['(?P<value>x)']
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    config.work_dir.mkdir(parents=True, exist_ok=True)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    with Database(config.database) as db:
        summary = export_stage(config, db)

    files = summary["files"]
    for name in ("results_csv", "review_csv", "long_csv"):
        assert name in files, f"缺 openpyxl 不该影响 CSV：files={sorted(files)}"
    assert "excel" not in files, "缺 openpyxl 时不应给出 excel 路径（那是坏路径）"

    reasons = " ".join(summary.get("warnings") or [])
    assert "openpyxl" in reasons, f"降级原因没提到 openpyxl：{reasons!r}"
    assert "pip install" in reasons, f"降级原因不可操作：{reasons!r}"
