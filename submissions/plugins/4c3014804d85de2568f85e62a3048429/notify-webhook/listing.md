# Webhook 任务通知

采集是长任务：站点多、页面多，跑起来可能几十分钟。你离开之后需要知道
「跑完了没有、成了多少条」—— 这个插件在任务结束时把终态摘要推到你配置的
Webhook，企业微信 / Slack / Discord / 自建服务都能接。

## 它做什么

任务进入**终态**（`succeeded` / `failed` / `cancelled`）时，向配置的 URL
发一个 `POST`，JSON 体形如：

```json
{
  "text": "任务 t-20261123-01 succeeded：成功 128 / 失败 3 / 跳过 5",
  "summary": {
    "task_id": "t-20261123-01",
    "status": "succeeded",
    "succeeded": 128,
    "failed": 3,
    "skipped": 5
  }
}
```

`text` 是给人看的一行；`summary` 是给机器解析的结构化字段。

## 配置

在配置的 `hook` / 插件 section 里给一个 `url`：

```yaml
plugins:
  notify-webhook:
    url: https://example.com/hooks/omnicrawler
    only_terminal: true      # 可选，默认 true
```

* **没配 `url`** ⇒ 静默跳过，不发任何请求。这是可选能力，缺配置是正常状态。
* **`only_terminal: false`** ⇒ 连 `running` / `pending` 也推（一般不建议，
  会产生大量中间态通知）。

## 边界（重要）

本插件**不自己发网络请求**。它只返回「要发的请求描述」，由宿主统一经
`EgressBroker` 发出 —— 所以仍然受项目的出网审计、robots、预算约束。
插件不得绕开这条硬边界。

这也是 `permissions: []` 的原因：它不碰凭据、不碰文件系统、不直连网络。

## 许可

MIT。
