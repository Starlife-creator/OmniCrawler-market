# Tideprint Gate（tideprint-gate）

版本：0.4.0 · 一致的语义变化检测 · 2026-10-04。发行包使用现有作者身份签名；修改载荷后必须重新签名。

## 功能

钩子的原始哈希与处理器语义哈希分开。处理器按策略摘要保存独立持久基线；文本空白规范化在两种启用路径中保持一致。JSON 支持显式字段忽略与数组排序；JSON 字符串内部空白保持语义。

## 配置与状态

normalize_text: true；json_ignore_fields: ['/time']；json_sort_arrays: ['/tags']。字段使用 JSON Pointer，最多 50 项，每项最多 500 字符与 32 层；启用 JSON 规范化时正文上限 8 MiB。策略变化建立新基线；旧 raw 基线继续用于 HTTP 重验证。

## 权限与数据去向

声明权限：state:read, state:write。保留 state schema 1，新增 semantic.v2 命名空间避免误读旧 raw 基线。只使用 hook 时是 raw_bytes 判定；processor 是 semantic 判定。304 不覆盖正文基线。正文区域 CSS 比较和跨插件正文复用需要另行设计，未纳入此版本。

## 兼容与许可

最低核心版本：0.11.2；执行模式：subprocess；许可：MIT。
