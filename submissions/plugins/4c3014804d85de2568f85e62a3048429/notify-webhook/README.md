# notify-webhook · 任务完成通知

采集任务结束（成功或失败）时，向配置的 Webhook 推一条终态摘要。

## 为什么需要

OmniCrawler 的采集是长任务（站点多、页面多、可能跑几十分钟）。用户离开之后
需要知道「跑完了没有、成了多少条」—— 现在只能回来自己看。

## 用法

```yaml
plugins:
  enabled_market_plugins: [notify-webhook]
hooks:
  task_finished:
    notify-webhook:
      url: https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...
      only_terminal: true     # 只在终态（完成/失败）推，running 不打扰
```

推送体：

```json
{"text": "任务 t-42 succeeded：成功 500 / 失败 3 / 跳过 12", "summary": {...}}
```

## ★ 一条硬边界：插件**不发请求**

插件只返回「要发的请求描述」，由宿主经 `EgressBroker` 真正发出 ——
egress 审计、robots、预算、凭据作用域全部由宿主负责。
插件不得绕开这条边界自己联网，所以 `permissions` 是空的。

## 两条判据

1. **没配 url 就不发**：这是可选能力，缺配置是正常状态，不是错误；
2. **非终态不打扰**：`running` / `pending` / `queued` 直接跳过；
   `only_terminal: false` 可关掉这条。

## 权限与数据去向

**零权限**。插件只产生请求描述：不联网、不读文件、不碰凭据。

## 兼容与许可

- OmniCrawler `>=0.7.0` · MIT

## 已知限制

- 不做重试：发送失败由宿主的重试策略处理。
- 不校验接收方是否真的收到（Webhook 通常不回有意义的状态）。
