# Chronicle Capsule

## 0.3.0 开发版（2026-10-03，待作者签名）

privacy/metadata 对敏感字段名、URL 用户信息与敏感查询参数、Bearer 及常见密钥赋值模式脱敏。正文模式无法保证识别任意个人信息或自定义秘密，summary.redaction_scope 会说明范围；preservation 不脱敏。

每条 WARC 独立 gzip 压缩；宿主只提供正文时使用 resource 记录，不伪造 HTTP 响应头。截断内容带 WARC-Truncated: length，并分别报告缺失、截断、完整载荷、容量、摘要和分页限制。导出超过 25 MiB 中止并撤销工件，不提交半份归档。每 25 项尝试上报进度，无面板时静默降级。

独立读取器 QA 使用 warcio（仅测试依赖，插件运行零依赖）；格式参考 https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1/ 。

以上为当前行为；下文旧版本内容保留为历史说明。


把一次采集封装为可复核的 WARC 1.1 归档。可选择结构化记录脱敏、响应元数据或原始正文保全，
并通过宿主不透明工件流有界写入。原始正文模式需要单独的高风险权限确认。
