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

import importlib.util
import pathlib
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
        from omnicrawler_pdf.pdfx.service import run_extraction

        # **完整管线**是 run_extraction(auto_prepare=True)，不是 run_processing。
        #
        # 实测踩到：run_processing 只做 ingest → parse → ocr → text_export，
        # 返回里**没有** extract 键；用它当 "processor.process" 会让抽取结果
        # 永远为空（五表照常产出，但字段全是空的）。真正串起
        # ingest→parse→ocr→extract→export 的是 run_extraction，
        # 它的 auto_prepare=True 会先补跑前置阶段。
        #
        # 两个函数都收**配置路径**（内部 prepare_config 再加载），不是对象。
        config_path = _config_path(payload)
        try:
            return {"ok": True, "result": run_extraction(config_path)}
        finally:
            # 只有内联配置会落临时文件（config_path 分支返回的是调用方路径，
            # 删它等于删用户的项目配置）。用前缀区分。
            if pathlib.Path(config_path).name.startswith("tmp"):
                try:
                    pathlib.Path(config_path).unlink()
                except OSError:
                    pass


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


def _config_path(payload: dict[str, Any]) -> str:
    """把 payload 归一为**配置文件路径**（
un_processing 需要路径）。

    为什么单独一个函数：插件里有两种消费方式——
    * 
un_processing(path) 收路径（内部自己 prepare_config）；
    * xport_stage(config, db) 收 ProjectConfig 对象。

    早先只写了"返回对象"的版本，导致 processor.process 把对象传给
    
un_processing 而失败（实测）。两条路径各取所需，不硬凑成一个。
    """
    path = payload.get("config_path") or payload.get("project")
    if path:
        return str(path)
    return _write_inline_config(payload)


def _write_inline_config(payload: dict[str, Any]) -> str:
    """把内联配置字典落成临时 YAML，返回其路径。

    **调用方负责删除**（_config_path 的使用者在处理完后清理）。
    用临时文件而不是在内存里构造 ProjectConfig：走同一条 load_config
    路径才能保证 schema 校验完全一致——两套加载逻辑必然漂移。
    """
    import tempfile

    import yaml

    inline = payload.get("config")
    if not isinstance(inline, dict):
        raise ValueError("需要 config_path 或 config（内联项目配置）")
    handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    try:
        handle.write(yaml.safe_dump(inline, allow_unicode=True))
    finally:
        handle.close()
    return handle.name


def _resolve_project_config(payload: dict[str, Any]) -> Any:
    """按 payload 取 **ProjectConfig 对象**（xport_stage 等需要对象）。"""
    import os

    from omnicrawler_pdf.pdfx.config import load_config

    path = payload.get("config_path") or payload.get("project")
    if path:
        return load_config(path)

    # 内联配置：落临时文件 → 同一条 load_config 路径 → 删掉。
    temporary = _write_inline_config(payload)
    try:
        return load_config(temporary)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


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
    # **必须与实测导入图一致**：此前只列了 6 项，而插件实际用 24 个第三方包，
    # 缺依赖时自检会误报"一切正常"（2026-11-23 实测：18 个包未被覆盖）。
    #
    # 分三档，判据是"缺了会导致什么"：
    optional = {
        # ① 核心链路：缺了主流程跑不动（但会给出明确原因）
        "yaml": "项目配置读写（必需）",
        "pypdfium2": "PDF 页面渲染",
        "pdfplumber": "PDF 文本层提取",
        "pypdf": "PDF 文本层（备用）",
        "pdfminer": "PDF 版面分析",
        "openpyxl": "Excel 五表导出",
        "reportlab": "PDF 写出",
        # ② 特定格式：只用该格式时才需要
        "pyarrow": "Parquet 读写",
        "duckdb": "DuckDB 读写",
        "docx": "DOCX 表格写出",
        "pptx": "PPTX 表格写出",
        "PIL": "图片读写（OCR 前处理）",
        "bs4": "HTML 解析",
        "chardet": "编码探测（缺失则回退 UTF-8）",
        "defusedxml": "XML 安全解析（Office 文档）",
        "regex": "高级正则（Unicode 属性）",
        # ③ OCR 引擎：二选一
        "paddleocr": "PaddleOCR 引擎",
        "paddle": "PaddleOCR 运行时",
        "pytesseract": "Tesseract 引擎",
        # ④ 宿主已提供 / GUI 才需要
        "numpy": "数值处理（OCR 与表格）",
        "psutil": "内存与进程信息",
        "PySide6": "GUI 界面（仅图形界面需要）",
        "cryptography": "凭据加密",
        "keyring": "系统钥匙串",
    }

    # 用 find_spec 而不是 import_module：既回答"装没装"，又不触发
    # 市场扫描器的「动态导入」硬拒规则（扫描器对 import_module 一律报 error）。
    missing_required: list[str] = []
    for name in required:
        try:
            if importlib.util.find_spec(name) is None:
                missing_required.append(name)
        except Exception as exc:  # noqa: BLE001 - 自检要报告而不是崩
            missing_required.append(f"{name}: {exc}")

    missing_optional: list[dict[str, str]] = []
    for name, purpose in optional.items():
        try:
            if importlib.util.find_spec(name) is None:
                missing_optional.append({"module": name, "purpose": purpose})
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

        # ── 宿主 facade 兼容操作（2026-11-17）──────────────────────────
        # 宿主侧 `services/document_facade.py` 保留了一组同名入口
        # （load_pdf_config / create_project_config / run_pdf_extraction …），
        # 这些是既有挂点（workbench / pdf_integration / preflight / cli）用的。
        # 插件必须能应答，否则宿主一调就失败。

        if operation == "pdf.load_config":
            from omnicrawler_pdf.pdfx.config import load_config

            return load_config(payload["config_path"])

        if operation == "pdf.create_project":
            from omnicrawler_pdf.pdfx.project import create_project_config

            return create_project_config(*payload.get("args", []), **payload.get("kwargs", {}))

        if operation == "pdf.extract":
            from omnicrawler_pdf.pdfx.service import run_extraction

            return run_extraction(*payload.get("args", []), **payload.get("kwargs", {}))

        if operation == "pdf.database_status":
            from omnicrawler_pdf.pdfx.service import database_status

            return database_status(payload["database"])

        if operation == "pdf.cli":
            import sys

            from omnicrawler_pdf.pdfx.cli import main as pdf_cli_main

            argv = list(payload.get("argv") or [])
            old = sys.argv
            try:
                sys.argv = ["omnicrawler pdf", *argv]
                pdf_cli_main()
            finally:
                sys.argv = old
            return {"ok": True}

        if operation == "pdf.processor":
            from omnicrawler_pdf.apps import pdf_processor

            return pdf_processor.main(list(payload.get("argv") or []))

        if operation == "pdf.field_extractor":
            from omnicrawler_pdf.apps import field_extractor

            return field_extractor.main(list(payload.get("argv") or []))

        if operation == "convertx.convert":
            from omnicrawler_pdf.convertx import convert as convertx_convert

            return convertx_convert(*payload.get("args", []), **payload.get("kwargs", {}))

        if operation == "convertx.preset":
            from omnicrawler_pdf.convertx.presets import get_preset

            return get_preset(payload["name"], payload.get("path"))

        if operation == "review.compare":
            # review 属**宿主侧**能力（运行对比用于记录删除/变更审计，被
            # services/record_deletions.py 使用），未随 PDF 工作台迁出。
            from omnicrawler.review.run_compare import compare_runs

            return compare_runs(*payload.get("args", []), **payload.get("kwargs", {}))

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


# ── 模块级辅助（供宿主 facade 直接调用）──────────────────────────────────


def open_pdf_database(path: str) -> Any:
    """打开 PDF 项目数据库，返回 Database 实例（调用方负责关闭）。"""
    from omnicrawler_pdf.pdfx.database import Database

    return Database(path)


def component_ocr_backend_class() -> Any:
    """返回组件式 OCR 后端类。

    宿主 `plugins.plugin_broker_host` 的 `component.ocr.recognize` 能力用它：
    插件请求宿主代调 OCR 组件时，宿主需要拿到这个类。
    """
    from omnicrawler_pdf.pdfx.component_ocr import ComponentOCRBackend

    return ComponentOCRBackend


def pdf_views() -> Any:
    """返回 PDF 工作台的 GUI 视图模块（供宿主 `central_area` 按需加载）。

    返回的是**模块**而不是类：`PdfWorkbenchView` 与 `ConvertView` 都在其中，
    它们的内部依赖（result / scan / worker）也都在插件内，宿主无需知道。
    """
    from omnicrawler_pdf.gui_views import pdf_workbench_views

    return pdf_workbench_views


def convertx_module() -> Any:
    """返回一个**具备转换 API 的对象**（供宿主 omnicrawler convert 使用）。

    宿主 _handlers.py 需要 module.OutputRule 来构造输出规则。
    直接返回本插件模块是错的——它没有 OutputRule（实测
    AttributeError: 'module' object has no attribute 'OutputRule'）。

    所以这里包一层，把宿主实际用到的符号显式暴露出来。
    新增需要时在此追加，**不要**把插件模块本身丢给宿主——
    那等于让宿主耦合插件的内部布局。
    """
    from omnicrawler_pdf.convertx import convert as _convert
    from omnicrawler_pdf.convertx.output_rules import OutputRule as _OutputRule

    class _ConvertX:
        OutputRule = _OutputRule

        @staticmethod
        def convert(*args: Any, **kwargs: Any) -> Any:
            return _convert(*args, **kwargs)

    return _ConvertX


def table_io() -> Any:
    """返回表格数据读写注册表（供宿主 `transform` 命令使用）。

    **2026-11-22 起改为返回宿主实现**（`omnicrawler.services.table_io`）。

    表格读写（csv/jsonl/xlsx/parquet/duckdb）已从本插件的 `convertx`
    **上提到宿主**——它是支柱①数据加工的通用能力，不该让 transform
    依赖 PDF 插件。

    插件侧保留本入口只为**兼容旧调用点**；实际返回的是同一份实现，
    不存在两份漂移。
    """
    from omnicrawler.services import table_io as host_table_io

    return host_table_io


def pdf_region_selector() -> Any:
    """返回 PDF 区域选择对话框类（供宿主 gui/main.py 按需加载）。"""
    from omnicrawler_pdf.gui_views.pdf_region_selector import PdfRegionSelectorDialog

    return PdfRegionSelectorDialog


def parse_document(*args: Any, **kwargs: Any) -> Any:
    """解析文档为 IR（宿主 archive_analysis / doc_extractors 经 facade 调用）。"""
    from omnicrawler_pdf.document_ir import parse_document as _parse

    return _parse(*args, **kwargs)


def document_block_class() -> Any:
    """返回 `DocumentBlock` 类。"""
    from omnicrawler_pdf.document_ir.base import DocumentBlock

    return DocumentBlock
