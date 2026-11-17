"""版本号：插件自带，不依赖宿主 `omnicrawler._version`。

插件有自己的版本（`plugin.yaml` 的 `version`），与宿主版本是两回事。
`pdfx` 里原本读宿主 `__version__` 的地方只是用于日志/产物元信息，
这里给插件侧一个独立常量，避免把宿主版本号烧进插件产物。
"""
from __future__ import annotations

#: 文档工作台插件自身的版本。与 `plugin.yaml` / `PLUGIN_METADATA` 保持一致，
#: 由守卫测试 `test_plugin_metadata_consistency` 钉住。
__version__ = "1.0.0"

__all__ = ["__version__"]
