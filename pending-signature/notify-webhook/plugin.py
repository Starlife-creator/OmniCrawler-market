"""Webhook 通知插件：采集任务完成/失败时回调外部 URL。

## 为什么需要

OmniCrawler 的采集是长任务（站点多、页面多、可能跑几十分钟）。用户离开
之后需要知道「跑完了没有、成了多少条」—— 现在只能回来自己看。

这个插件在 `hook.task_finished` 时向用户配置的 Webhook 发一个 POST，
把任务的终态摘要推出去（企业微信/Slack/Discord/自建服务都能接）。

## 契约约束（照抄 `example_news` 的写法）

* 运行于**隔离沙箱子进程**，**不能 import omnicrawler**；
  一切输入经 `payload["config"]` / `payload` 传入。
* 只做纯逻辑：**不自己发网络请求**，而是返回「要发的请求」交给宿主
  （宿主负责 egress 审计与 robots/预算控制）—— 这条是本项目的硬边界，
  插件不得绕开 `EgressBroker`。
* `permissions` 声明为空：本插件只产生请求描述，不触碰凭据与文件系统。
"""

PLUGIN_METADATA = {
    "name": "notify-webhook",
    "version": "1.0.0",
    "description": "任务结束时向配置的 Webhook 推送终态摘要（成功/失败/计数）",
    "plugin_types": ["hook"],
    "permissions": [],
    "license": "MIT",
    "execution_mode": "subprocess",
}

#: 默认超时与重试。写在模块级便于测试直接读。
DEFAULT_TIMEOUT_SECONDS = 10


def _summarize(payload: dict) -> dict:
    """从 payload 里抽出终态摘要。缺字段时给安全默认值，不抛异常。"""
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    return {
        "task_id": str(task.get("id") or payload.get("task_id") or ""),
        "status": str(task.get("status") or payload.get("status") or "unknown"),
        "succeeded": int(stats.get("succeeded") or payload.get("succeeded") or 0),
        "failed": int(stats.get("failed") or payload.get("failed") or 0),
        "skipped": int(stats.get("skipped") or payload.get("skipped") or 0),
    }


def _render_text(summary: dict) -> str:
    """把摘要渲染成一行中文，供聊天工具直接展示。"""
    return (
        f"任务 {summary['task_id'] or '(未知)'} {summary['status']}："
        f"成功 {summary['succeeded']} / 失败 {summary['failed']} / "
        f"跳过 {summary['skipped']}"
    )


def handle(operation, payload):
    """契约 2 入口。

    `hook.task_finished` ⇒ 返回一条待发请求；其余操作原样回显（不报错，
    因为宿主可能对所有 hook 广播同一批操作）。
    """
    if operation != "hook.task_finished":
        return {"operation": operation}

    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    url = str(config.get("url") or "").strip()
    if not url:
        # **没有配置就不发**：这是可选能力，缺配置是正常状态而不是错误。
        return {"requests": [], "skipped": "未配置 webhook url"}

    summary = _summarize(payload)
    # 只推「用户关心的终态」：running/pending 不打扰。
    if str(config.get("only_terminal", True)).lower() in ("false", "0", "no"):
        pass
    elif summary["status"] in ("running", "pending", "queued"):
        return {"requests": [], "skipped": f"非终态：{summary['status']}"}

    body = {
        "text": _render_text(summary),
        "summary": summary,
    }
    return {
        "requests": [
            {
                "url": url,
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json",
                    # 让接收方能识别来源与版本，便于排查
                    "User-Agent": "OmniCrawler-notify-webhook/1.0.0",
                },
                "json": body,
                "kind": "webhook",
                "meta": {"task_id": summary["task_id"]},
            }
        ]
    }
