"""插件内的宿主兼容层（契约 2 禁止 `import omnicrawler`）。

为什么需要这一层
----------------
文档工作台原本是宿主的一部分，它依赖若干**自己并不拥有**的工具模块：

```
core.builtin_references   内置模板引用解析
core.safe_data            JSON 安全加载
core.encoding             自动编码探测
core.utils                原子写、Excel 安全化、UA
i18n                      翻译
_version                  版本号
```

契约 2 规定插件**不得 `import omnicrawler`**，所以这些必须换成插件内实现。

选择：**复制纯函数实现，而不是经 SDK 代理**。理由：

* 这几个模块是**纯工具**（字符串/JSON/编码/文件原子写），没有宿主状态、
  没有数据库、没有配置系统。走 SDK 代理要为每个函数加一次 IPC 往返，
  既慢又增加协议面；
* 它们的行为必须与宿主**逐字一致**（否则同一个 PDF 在插件版和宿主版
  会算出不同结果），复制+守卫测试比代理更能保证这一点；
* 复制的是**小块纯逻辑**（合计约 26 KB），不是业务。

不复制的东西
------------
`core.config`（ProjectConfig，整个应用的配置系统）与 `security.paths`
**不复制**——它们与宿主语义强耦合。PDF 插件改为**自己定义配置模型**，
只保留它实际需要的字段（见 `pdfx.config`）。
"""
from __future__ import annotations

from .builtin_references import (
    BUILTIN_PDF_PREFIX,
    DEFAULT_PDF_TEMPLATE,
    LEGACY_DEFAULT_PDF_TEMPLATE,
    builtin_pdf_resource,
    is_builtin_pdf_reference,
    resolve_builtin_pdf_reference,
)
from .encoding import read_text_auto
from .safe_data import safe_json_loads
from .utils import atomic_write_text, excel_safe, user_agent

__all__ = [
    "BUILTIN_PDF_PREFIX",
    "DEFAULT_PDF_TEMPLATE",
    "LEGACY_DEFAULT_PDF_TEMPLATE",
    "atomic_write_text",
    "builtin_pdf_resource",
    "excel_safe",
    "is_builtin_pdf_reference",
    "read_text_auto",
    "resolve_builtin_pdf_reference",
    "safe_json_loads",
    "user_agent",
]
