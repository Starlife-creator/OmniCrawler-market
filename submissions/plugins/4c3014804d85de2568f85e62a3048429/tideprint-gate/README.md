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

## 历史使用参考

以下保留此前版本使用说明；旧版权限、版本和行为描述仅作历史参考，当前行为以本文上方说明为准。

# Tideprint Gate（潮印门）

## 0.3.0 开发版（2026-10-03，待作者签名）

损坏或缺失 Base64 正文标记 invalid，不更新指纹；明确的文本 MIME 类型才压缩空白，未知类型与二进制使用原始字节。错误响应不覆盖成功指纹，304 保留原摘要。重定向同时保存入口与终点键；processor 复用 hook 的持久变化分类，汇总分别给出 current_run_counts 与 persistent_counts。

以上为当前行为；下文旧版本内容保留为历史说明。


用规范化 URL 与 SHA-256 内容指纹标记 `new`、`unchanged`、`changed`，并在运行结束 Hook
返回汇总。当前运行仍使用最多 10,000 个 URL 的内存状态，跨运行指纹则写入宿主受控状态空间。

`before_fetch` 只向宿主建议条件重验证；是否添加宿主保存的 ETag/Last-Modified、是否继续抓取，
始终由应用本体裁决。`after_fetch` 只保存摘要和规范化 URL，不保存正文。状态按项目、插件 ID、
作者指纹与状态 schema 隔离，插件更新不会复用其他作者的状态。

思路借鉴 scrapy-deltafetch 的稳定指纹与增量门禁方法论，代码完全独立实现。
