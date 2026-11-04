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
