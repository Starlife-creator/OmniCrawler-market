"""契约 2 子进程插件样板（Phase 2a 市场示例）。

示例：为入口请求强制附加站点所需请求头并打站点标记。
契约 2 插件运行于隔离沙箱子进程，**不能 import omnicrawler**——
seed 逻辑自包含，宿主经能力代理传入 ``payload["config"]``
（即配置 ``source`` 节）。复制本文件即可开始编写真实网站适配器。
"""

PLUGIN_METADATA = {
    "name": "example_news",
    "version": "1.1.0",
    "description": "示例新闻站点适配器：入口附加 XHR 请求头 + 站点打标",
    "plugin_types": ["source"],
    "permissions": [],
    "license": "MIT",
    "execution_mode": "subprocess",
    #: 门 3 要求显式声明（零依赖也要写 []），且必须与实测导入图互证。
    "dependencies": [],
}


def handle(operation, payload):
    if operation == "source.seed":
        config = payload.get("config", {})
        requests = []
        for raw in config.get("seeds", []):
            if isinstance(raw, dict):
                url = str(raw.get("url", ""))
                method = str(raw.get("method", "GET")).upper()
                headers = {str(k): str(v) for k, v in raw.get("headers", {}).items()}
            else:
                # ★ 2026-11-27 修：`None` 会被 `str()` 变成字符串 `"None"`，
                #   于是产出一条 `url="None"` 的假请求 —— 一个"看起来有值"的坏 URL。
                #   契约 2 的样板是给后来者抄的，这种坑必须在样板里就没有。
                if raw is None:
                    continue
                url = str(raw).strip()
                method = str(config.get("method", "GET")).upper()
                headers = {str(k): str(v) for k, v in config.get("headers", {}).items()}
            if not url or not url.strip():
                continue
            headers["X-Requested-With"] = "XMLHttpRequest"
            requests.append({
                "url": url,
                "method": method,
                "headers": headers,
                "kind": "page",
                "meta": {"root_url": url, "site": "example_news"},
            })
        return {"requests": requests}
    return {"operation": operation}