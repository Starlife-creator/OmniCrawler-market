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
