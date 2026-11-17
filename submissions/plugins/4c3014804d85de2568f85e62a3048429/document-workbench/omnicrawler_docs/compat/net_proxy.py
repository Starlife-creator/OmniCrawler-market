"""出网代理（插件侧）：所有网络请求经宿主 `network.fetch`。

为什么插件不能直连
------------------
仓库原则 2：**采集网络路径一律经 `EgressBroker`，且缺省 fail-closed**。
插件运行在受沙箱约束的子进程里，如果允许它裸用 `urllib`/`requests`：

* 绕过了出网预算与审计（谁在什么时候访问了什么，宿主不再掌握）；
* 绕过了域名白名单（`domains` 声明失效）；
* 绕过了凭据隔离（插件可能读到宿主的密钥）。

所以本模块把原本 `security.controlled_http.scoped_json_request` 的调用
**整体换成一次 SDK 调用**，签名保持兼容——调用方（`pdfx/llm.py`）不需要改。

与宿主版的行为差异（明确写出来，不假装一致）
--------------------------------------------
| 维度 | 宿主版 `scoped_json_request` | 本模块（经代理） |
|---|---|---|
| 出网执行者 | 当前进程 | **宿主进程** |
| 域名校验 | 本地 workspace 作用域 | 宿主按 manifest `domains` 校验 |
| 响应大小上限 | 本地截断 | 宿主截断后回传 |
| 凭据 | 调用方构造 Authorization | 同（但宿主不落日志） |

`workspace` 参数保留但不参与出网决策——作用域判定改由宿主做，
插件不应自己声称"我在哪个 workspace 里"。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any


def _sdk_call(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    """惰性调用宿主能力代理（无宿主环境时给出明确错误）。"""
    try:
        import omnicrawler_sdk  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "本插件必须在 OmniCrawler 宿主内运行：找不到 omnicrawler_sdk 能力代理。"
        ) from exc
    return omnicrawler_sdk.call(operation, payload)


def scoped_json_request(
    url: str,
    *,
    workspace: Path | str | None = None,
    purpose: str = "ai",
    method: str = "POST",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout_seconds: float = 60.0,
    max_response_bytes: int = 4 * 1024 * 1024,
    user_agent: str = "",
) -> dict[str, Any]:
    """经宿主代理发一次 HTTP 请求并把响应解析为 JSON。

    签名与原 `security.controlled_http.scoped_json_request` **保持一致**，
    这样 `pdfx/llm.py` 只需换导入来源，调用点零改动。

    返回解析后的 JSON 对象；非 2xx、非 JSON、超限都抛 `RuntimeError`
    （与宿主版一致：不把错误包成"看起来成功"的返回值）。
    """
    payload: dict[str, Any] = {
        "url": str(url),
        "method": str(method).upper(),
        "headers": dict(headers or {}),
        "timeout_seconds": float(timeout_seconds),
        "max_response_bytes": int(max_response_bytes),
        "purpose": str(purpose),
    }
    if user_agent:
        payload["user_agent"] = str(user_agent)
    if body is not None:
        payload["body_base64"] = base64.b64encode(body).decode("ascii")

    response = _sdk_call("network.fetch", payload)

    status = int(response.get("status", 0) or 0)
    if status and not (200 <= status < 300):
        raise RuntimeError(f"HTTP {status}: {str(response.get('body') or '')[:500]}")

    raw = response.get("body_base64")
    if raw:
        try:
            decoded = base64.b64decode(raw, validate=True)
        except Exception as exc:  # noqa: BLE001 - 代理回传损坏属协议错误
            raise RuntimeError(f"网络代理回传的响应体不是合法 base64: {exc}") from exc
    else:
        text = response.get("body")
        decoded = text.encode("utf-8") if isinstance(text, str) else bytes(text or b"")

    if max_response_bytes and len(decoded) > max_response_bytes:
        raise RuntimeError(
            f"响应超过上限：{len(decoded)} > {max_response_bytes} 字节"
        )

    try:
        parsed = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"响应不是合法 JSON：{decoded[:200]!r}（{type(exc).__name__}）"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"响应 JSON 顶层必须是对象，实际是 {type(parsed).__name__}")
    return parsed
