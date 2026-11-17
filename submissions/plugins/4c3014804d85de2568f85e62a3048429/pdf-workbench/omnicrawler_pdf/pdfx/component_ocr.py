"""组件式 OCR 后端（插件侧）：**经 SDK 请宿主代调**。

与宿主版的关键差异
------------------
宿主版（`omnicrawler/pdfx/component_ocr.py`）自己做了四件事：

1. 读信任根验签；
2. 拿跨进程注册表锁做租赁；
3. 裁剪环境变量后启动组件子进程；
4. 解析组件回传的 JSON。

**插件版只做第 4 件事的一半**——交 PNG、收文本。前三件全部交给宿主：

```
插件 (本文件)                   宿主 (plugin_broker_host)
  omnicrawler_sdk.call(  ───►  _cap_component_ocr_recognize
      "component.ocr.recognize",     ├─ 验签（信任根只在宿主）
      {png_base64, engine, ...}      ├─ 租赁（注册表锁只在宿主）
  )                                  ├─ 启动组件子进程（裁剪环境）
  ◄─── {text, confidence}            └─ 回传文本
```

为什么这样分
------------
信任根、注册表锁、进程环境都属于**宿主特权**。插件是受沙箱约束的子进程，
一旦让它自己做，等于把安全边界下移到不受控进程 —— 与项目「安全与隔离」
原则直接冲突。

代价与取舍
----------
* 每次识别多一次 IPC（JSON 往返）。相对 OCR 本身的耗时（百毫秒到秒级），
  这点开销可忽略；
* PNG 要 base64 编码后传输，体积增大约 1/3。所以仍保留 **20 MB 上限**
  （与宿主侧一致），超限直接拒绝而不是硬传。
"""
from __future__ import annotations

import base64
import math
from typing import Any

from .ocr_result import OCRRichResult

#: PNG 字节上限：与宿主侧 `BrokerComponentOcrMixin._OCR_MAX_PNG_BYTES` 一致。
#: 两处都要检查——插件侧早失败的目的是**省一次 IPC 与内存占用**，
#: 不是替代宿主侧的校验（宿主侧必须独立校验）。
MAX_PNG_BYTES = 20 * 1024 * 1024

#: PNG 魔数。
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _sdk_call(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """调用宿主能力代理。

    **不能在模块顶层 import `omnicrawler_sdk`**：该模块由宿主在运行时注入到
    `sys.modules`，独立运行（如单元测试、`python plugin.py`）时并不存在。
    这里做惰性导入，让本模块在无宿主环境下也能被导入与静态检查。
    """
    try:
        import omnicrawler_sdk  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "本插件必须在 OmniCrawler 宿主内运行："
            "找不到 omnicrawler_sdk 能力代理。"
        ) from exc
    return omnicrawler_sdk.call(operation, payload)


class ComponentOCRBackend:
    """通过宿主代理调用已验签的离线 OCR 组件。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.component = str(config.get("component", "")).strip()
        if not self.component:
            raise ValueError("组件式 OCR 需要指定 component 名称")
        self.engine = str(config.get("backend", "paddle")).lower()
        self.lang = str(config.get("lang", "ch"))
        self.timeout = float(config.get("component_timeout_seconds", 120))
        if not math.isfinite(self.timeout) or not 0 < self.timeout <= 600:
            raise ValueError("OCR组件超时须在 0 到 600 秒之间")
        #: 宿主在首次调用后回传的组件版本；用于检测"跑到一半组件被升级"。
        self.version = ""

    def recognize(self, png_bytes: bytes) -> tuple[str, float | None]:
        result = self.recognize_rich(png_bytes)
        return result.text, result.confidence

    def recognize_rich(self, png_bytes: bytes) -> OCRRichResult:
        # 插件侧的**早失败**：省一次 IPC 与大块内存，不替代宿主校验。
        if not png_bytes.startswith(PNG_MAGIC) or len(png_bytes) > MAX_PNG_BYTES:
            raise ValueError("OCR组件只接收大小受限的 PNG 输入")

        response = _sdk_call(
            "component.ocr.recognize",
            {
                "component": self.component,
                "engine": self.engine,
                "lang": self.lang,
                "png_base64": base64.b64encode(png_bytes).decode("ascii"),
            },
        )

        # 宿主回传的 version 用于检测"任务跑到一半组件被换掉"。
        version = str(response.get("version", "") or "")
        if version:
            if not self.version:
                self.version = version
            elif version != self.version:
                raise RuntimeError("OCR组件版本已改变，请重新开始任务")

        text = str(response.get("text", "") or "")
        raw_confidence = response.get("confidence")
        confidence: float | None
        if raw_confidence is None:
            confidence = None
        else:
            confidence = float(raw_confidence)
            if not math.isfinite(confidence):
                confidence = None
        return OCRRichResult(text, confidence)
