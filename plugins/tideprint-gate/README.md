# Tideprint Gate（潮印门）

用规范化 URL 与 SHA-256 内容指纹标记 `new`、`unchanged`、`changed`，并在运行结束 Hook
返回汇总。当前运行仍使用最多 10,000 个 URL 的内存状态，跨运行指纹则写入宿主受控状态空间。

`before_fetch` 只向宿主建议条件重验证；是否添加宿主保存的 ETag/Last-Modified、是否继续抓取，
始终由应用本体裁决。`after_fetch` 只保存摘要和规范化 URL，不保存正文。状态按项目、插件 ID、
作者指纹与状态 schema 隔离，插件更新不会复用其他作者的状态。

思路借鉴 scrapy-deltafetch 的稳定指纹与增量门禁方法论，代码完全独立实现。
