"""PDF 工作台 GUI 视图聚合导出。

迁移后（2026-11-17）：原先住在宿主 `gui/views/` 的 PDF 相关视图迁到插件。
宿主 `central_area` 经 `document_facade.pdf_views()` 拿到本模块，
只取两个入口类：

* `PdfWorkbenchView` —— PDF 工作台主页面
* `ConvertView` —— 格式互转页面

**为什么返回模块而不是直接给两个类**：视图之间的内部依赖
（`pdf_workbench_result` / `pdf_workbench_scan` / `pdf_workbench_worker` /
`pdf_region_selector` / `pdf_layout_review`）都属于插件内部结构，
宿主不该知道。聚合在这里，宿主只认这两个名字。
"""
from __future__ import annotations

from .convert_tool import ConvertView
from .pdf_workbench import PdfWorkbenchView

__all__ = ["ConvertView", "PdfWorkbenchView"]
