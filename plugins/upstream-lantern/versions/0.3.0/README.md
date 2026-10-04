# Upstream Lantern（upstream-lantern）

版本：0.3.0 · 稳定事件与基线策略 · 2026-10-04。发行包使用现有作者身份签名；修改载荷后必须重新签名。

## 功能

输出稳定 event_id、policy_id、initial_baseline、event_kind。相同实体从失败变为成功产生 recovery 事件；重复观察不重复 attention。

## 配置与状态

source.params.track_changes: true；initial_policy: notify（默认）/ baseline；include_prereleases: true（默认）/ false。首次 baseline 仅建基线，不触发 attention；草稿发行始终忽略。使用 schema 1 内 lantern.v3 命名空间保存带摘要与结论的状态，策略切换独立建基线。默认策略会读取旧摘要并迁移，避免升级后重复提示历史事件。

## 权限与数据去向

声明权限：state:read, state:write。state 状态代表已观察，不能代表通知已投递。本插件不直接发送通知；下游需按 event_id 保存待发送事件与确认状态以支持失败重试。恢复识别针对同一 workflow run 实体；不同 run 的服务恢复聚合另行设计。

## 兼容与许可

最低核心版本：0.11.2；执行模式：subprocess；许可：MIT。

## 历史使用参考

以下保留此前版本使用说明；旧版权限、版本和行为描述仅作历史参考，当前行为以本文上方说明为准。

# Upstream Lantern

## 0.2.0 开发版（2026-10-03，待作者签名）

新增 extractor 形态，输出 upstream_signal 与 upstream_error，覆盖仓库、发布、标签、提交、社区健康、工作流与公告。错误结果明确 complete=false，不代表无更新或无风险。

source.params.adaptive_pagination=true 时仅生成第一页；extractor 对满页响应继续生成下一页，空页停止，pages/max_requests 预留最坏请求预算仍生效。必须同时配置 upstream-lantern 作为 extractor；固定分页仍为默认。只延续插件生成的 api.github.com 固定端点，不接受服务端任意分页 URL。

source.params.track_changes=true 使用宿主隔离状态对实体比较，输出 new/changed/unchanged；状态能力不可用时标记 tracking_unavailable。新增 state:read/state:write 权限。attention=true 表示新增或变化的发布/公告，或失败工作流；首次观测按 new 处理。通知由宿主配置消费 attention 字段。

示例：
```yaml
source:
  kind: upstream-lantern
  seeds: [psf/requests]
  params:
    feeds: [releases, workflow_runs]
    pages: 3
    max_requests: 6
    adaptive_pagination: true
    track_changes: true
extract:
  extractor: upstream-lantern
crawl:
  allow_domains: [api.github.com]
  max_pages: 6
  max_depth: 2
egress:
  allowed_domains: [api.github.com]
```
完整配置见 examples/monitor.yaml；examples/notify_updates.py 将 JSONL 中 attention=true 的记录转为本地通知摘要，不发送外部消息。签名完成后再按正常插件加载流程启用。

以上为当前行为；下文旧版本内容保留为历史说明。


Upstream Lantern（上游灯塔）是一个独立的 OmniCrawler 契约 2 源插件。它把用户明确配置的
GitHub 仓库转换为有限、可审查的 `api.github.com` 只读请求，用于观察发布、标签、提交、
社区健康度、GitHub Actions 和指定软件包的 Reviewed 安全公告。

本插件不直接联网，不执行下载内容，不读取本地文件，不包含第三方依赖，运行权限声明为空。
完整功能、配置示例、安全边界、认证方式和已知限制见 [listing.md](listing.md)。

## 当前状态

版本：`0.1.0`。许可：MIT。

在生成 `creator.identity`、`package.manifest.json` 和
`package.manifest.creator.sig` 之前，本目录只是未签名开发包，不应作为可信插件分发。
创作者整包签名完成后，它既可以直接私下分享，也可以原样投稿 OmniCrawler 市场。

无论采用哪种分发方式，都不要在目录中放入 Token、Cookie、私钥、`.env` 或真实配置文件。
