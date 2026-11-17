"""PDF Workbench —— 契约 1（`register`）插件入口，运行于 in_process。

为什么是契约 1 而不是契约 2
--------------------------
契约 2（`handle` + subprocess）**不适合文件工作台**，这不是取舍而是硬冲突：
宿主审计器 `gate_host_boundaries` 对 subprocess 插件的限制是

```
36 处 gate1_uncontrolled_file_io   直接读写文件
```

而 PDF 工作台的核心动作**就是**自由读写文件：打开用户选的 PDF、
把五张表写到项目输出目录、在项目旁建 SQLite 库。契约 2 给出的
`files.read`（静态白名单）、`artifact.stream`（不透明、无路径）、
`temp.open`（会话临时）**没有一条能覆盖这三件事**。

要么把整个项目目录塞进白名单（那权限声明就成了摆设），
要么把每次文件操作都做成 SDK 能力（IPC 传二进制、性能不可接受）。
两条路都让契约失去意义。

契约 1 的设计意图正是这类需求：**经单独审批的受信任代码**，运行在宿主进程内。
`gate_host_boundaries` 对 `execution_mode: in_process` 直接 `return []`
（见 `plugin_audit.py:745`）——这是**有意的豁免**，不是绕过。

代价（必须写清楚，不隐瞒）
--------------------------
* **没有子进程隔离**：本插件与宿主同进程，bug 或恶意代码能直接影响宿主；
* **不接受公共市场投稿**：`PLUGIN_CONTRACT.md` 明确「契约 1 仅供明确受信任的
  本地扩展；不接受公共市场投稿」；
* 需要**逐台机器审批**：`plugins.in_process_allowlist` 条目要带 `expires`，
  且插件必须位于 `plugins.trusted_local_dirs` 内（否则 fail-closed 降级 subprocess）。

换取的是：**功能与内置版完全一致**（同一套 `pdfx` 代码，不经 IPC）。

安全边界（仍然生效的部分）
--------------------------
即使 in_process，下面这些**依然照旧**，不受本插件形态影响：

* 组件 OCR 仍经 `ComponentOCRBackend`，验签/注册表锁仍由宿主执行；
* LLM 出网仍受隐私闸门约束（`allow_pdf_content` 未开启即拒发）；
* 插件加载前仍要**签名验签**（`plugin_trust.pub.pem`）与静态审计。
"""
from __future__ import annotations

import traceback
from typing import Any

PLUGIN_METADATA = {
    "name": "pdf-workbench",
    "version": "1.0.0",
    "api_version": 1,
    "description": "十万级 PDF 结构化数据抽取工作台——摄取、解析、OCR、字段抽取、复核与五表导出",
    "plugin_types": ["processor", "exporter"],
    "category": "document-processing",
    "tags": ["pdf", "ocr", "extraction", "table", "workbench"],
    # in_process 下不经过能力代理，所以"网络/文件"权限不适用；
    # 保留声明是为了让市场页能如实展示"此插件会读写本机文件"。
    "permissions": [],
    "domains": [],
    "input_files": [],
    # 依赖声明格式为 [{name, version, license}]（`plugin_audit.gate_dependencies_consistency`）。
    # `omnicrawler_pdf` 是本插件自带的包（实测导入会触发"未声明"检查，必须列出）；
    # `yaml` 是 PDF 项目配置解析的硬依赖。
    "dependencies": [
        {"name": "omnicrawler_pdf", "version": "1.0.0", "license": "Apache-2.0"},
        {"name": "yaml", "version": ">=6", "license": "MIT"},
    ],
    "license": "Apache-2.0",
    "execution_mode": "in_process",
    "min_core_version": "1.0.2",
}


class PDFWorkbenchProcessor:
    """`processor` 类型适配器：把 PDF 主流程暴露给管线。

    为什么用**工厂 + 实例**而不是直接注册函数：宿主 `Registry` 存的是
    `Factory`（可调用对象），每次任务取一个新实例，避免跨任务串状态。
    """

    name = "pdf_workbench"

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        """执行 PDF 处理主流程。参数与返回值语义见 `README.md`。"""
        from omnicrawler_pdf.pdfx.service import run_processing

        config = _resolve_project_config(payload)
        return {"ok": True, "result": run_processing(config)}


class PDFWorkbenchExporter:
    """`exporter` 类型适配器：五表导出。"""

    name = "pdf_workbench_export"

    def export(self, payload: dict[str, Any]) -> dict[str, Any]:
        from omnicrawler_pdf.pdfx.database import Database
        from omnicrawler_pdf.pdfx.exporter import export_stage

        config = _resolve_project_config(payload)
        with Database(config.database) as db:
            summary = export_stage(config, db)
        return {"ok": True, "summary": summary, "artifact_path": summary.get("files")}


def _resolve_project_config(payload: dict[str, Any]) -> Any:
    """按 payload 取 PDF 项目配置（路径优先，其次内联字典）。"""
    from omnicrawler_pdf.pdfx.config import load_config

    path = payload.get("config_path") or payload.get("project")
    if path:
        return load_config(path)

    inline = payload.get("config")
    if isinstance(inline, dict):
        import os
        import tempfile

        import yaml

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        try:
            handle.write(yaml.safe_dump(inline, allow_unicode=True))
        finally:
            handle.close()
        try:
            return load_config(handle.name)
        finally:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
    raise ValueError("需要 config_path 或 config（内联项目配置）")


def selfcheck() -> dict[str, Any]:
    """插件自检：报告缺失的必需/可选依赖。

    这项存在的理由：插件装在用户机器上，缺 `openpyxl`/`pypdfium2` 之类
    可选依赖时，用户看到的应该是"缺少 X，请安装"，而不是一个 ImportError 栈。
    """
    import importlib

    required = [
        "omnicrawler_pdf.pdfx.config",
        "omnicrawler_pdf.pdfx.database",
        "omnicrawler_pdf.pdfx.parser",
        "omnicrawler_pdf.pdfx.service",
    ]
    optional = {
        "pypdfium2": "PDF 页面渲染（OCR 需要）",
        "pdfplumber": "PDF 文本层提取",
        "openpyxl": "Excel 五表导出",
        "reportlab": "PDF 写出",
        "paddleocr": "PaddleOCR 引擎",
        "pytesseract": "Tesseract 引擎",
    }

    missing_required: list[str] = []
    for name in required:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - 自检要报告而不是崩
            missing_required.append(f"{name}: {exc}")

    missing_optional: list[dict[str, str]] = []
    for name, purpose in optional.items():
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001
            missing_optional.append({"module": name, "purpose": purpose})

    return {
        "ok": not missing_required,
        "required_missing": missing_required,
        "optional_missing": missing_optional,
        "version": PLUGIN_METADATA["version"],
    }


def register(registry: Any, context: Any = None) -> None:
    """契约 1 入口：把 PDF 工作台的能力注册进宿主。

    `registry` 是宿主 `Registry` 实例，提供 `register_processor` /
    `register_exporter` 等方法。`context` 可选（加载器支持两种签名）。

    注册的是**工厂**（lambda 返回新实例），不是实例本身：
    宿主按任务取实例，避免跨任务串状态。
    """
    registry.register_processor("pdf_workbench", lambda: PDFWorkbenchProcessor())
    registry.register_exporter("pdf_workbench", lambda: PDFWorkbenchExporter())


#: 供宿主/诊断调用「自检」的约定名（与 `PLUGIN_METADATA` 一起被静态读取）。
PDF_WORKBENCH_SELFCHECK = selfcheck


def run_operation(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """非注册类的辅助操作入口（自检 / 校验 / 状态 / 复核）。

    **为什么还要这个**：`register` 只能注册管线组件（processor/exporter），
    而工作台还有"校验配置""查状态""应用复核"这类一次性操作，
    它们不属于管线阶段。宿主诊断或 GUI 可直接调用本函数。

    任何异常都不外抛——多数失败（配置错误、缺依赖、组件未装）是可恢复的，
    应该让用户看到原因继续操作，而不是让宿主当成崩溃。
    """
    try:
        if operation == "pdf.selfcheck":
            return selfcheck()

        if operation == "pdf.validate":
            from omnicrawler_pdf.pdfx.config import validate_runtime_config

            config = _resolve_project_config(payload)
            problems = validate_runtime_config(config)
            return {"ok": not problems, "problems": problems}

        if operation == "pdf.status":
            from omnicrawler_pdf.pdfx.database import Database
            from omnicrawler_pdf.pdfx.service import database_status

            config = _resolve_project_config(payload)
            with Database(config.database) as db:
                return {"ok": True, "status": database_status(db)}

        if operation == "pdf.apply_review":
            from omnicrawler_pdf.pdfx.database import Database
            from omnicrawler_pdf.pdfx.review import apply_review

            config = _resolve_project_config(payload)
            review = dict(payload.get("review") or {})
            with Database(config.database) as db:
                result = apply_review(config, db, review)
            return {"ok": True, "result": result}

        if operation == "processor.process":
            return PDFWorkbenchProcessor().process(payload)

        if operation == "exporter.export":
            return PDFWorkbenchExporter().export(payload)

        return {
            "ok": False,
            "error": {"code": "unsupported_operation", "message": operation},
        }
    except Exception as exc:  # noqa: BLE001 - 插件边界：不把栈丢给宿主
        traceback.print_exc()
        return {
            "ok": False,
            "error": {
                "code": "plugin_failure",
                "message": f"{type(exc).__name__}: {exc}",
            },
        }
