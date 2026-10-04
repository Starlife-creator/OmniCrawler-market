# Chronicle Capsule（chronicle-capsule）

版本：0.4.0 · 准确摘要与 WARC 内索引 · 2026-10-04。发行包使用现有作者身份签名；修改载荷后必须重新签名。

## 功能

分别统计 scanned_inputs、业务 records、missing_payloads、truncated_payloads。输出输入上限、是否仍有后续数据及终止原因；同一 WARC 增加 metadata 索引记录，关联 Record-ID、来源、载荷摘要和截断状态。

## 配置与状态

mode: privacy / metadata / preservation；max_records 默认 1000，最多 5000。summary.records 为业务记录数，system_records=1 为索引记录。索引与正文合计受 25 MiB 未压缩限制，超限会 abort，不提交半套产物。

## 权限与数据去向

声明权限：records:read, responses:read, responses:payload, artifacts:write。privacy/metadata 索引随正文脱敏；preservation 明确保留响应正文，属于 body-only resource，不是完整 HTTP 响应或动态页面离线镜像。正文获取异常中止并 abort；缺失引用或无效 base64 计为 missing_payloads。

## 兼容与许可

最低核心版本：0.11.2；执行模式：subprocess；许可：MIT。

## 历史使用参考

以下保留此前版本使用说明；旧版权限、版本和行为描述仅作历史参考，当前行为以本文上方说明为准。

# Chronicle Capsule（时光胶囊）

## 0.3.0 开发版（2026-10-03，待作者签名）

privacy/metadata 对敏感字段名、URL 用户信息与敏感查询参数、Bearer 及常见密钥赋值模式脱敏。正文模式无法保证识别任意个人信息或自定义秘密，summary.redaction_scope 会说明范围；preservation 不脱敏。

每条 WARC 独立 gzip 压缩；宿主只提供正文时使用 resource 记录，不伪造 HTTP 响应头。截断内容带 WARC-Truncated: length，并分别报告缺失、截断、完整载荷、容量、摘要和分页限制。导出超过 25 MiB 中止并撤销工件，不提交半份归档。每 25 项尝试上报进度，无面板时静默降级。

独立读取器 QA 使用 warcio（仅测试依赖，插件运行零依赖）；格式参考 https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1/ 。

以上为当前行为；下文旧版本内容保留为历史说明。


将 OmniCrawler 当前运行内容导出为 `.warc.gz`。支持三种显式模式：`privacy` 对结构化记录递归
脱敏，`metadata` 仅保存响应元数据，`preservation` 保存由用户单独授权读取的原始响应正文。

插件使用单次不透明游标分页，最多处理 5,000 项；通过宿主不透明工件流分块写入，看不到输出
路径，也不能覆盖现有文件。每条记录携带 SHA-256，未压缩载荷硬限制为 25 MiB。原始保全权限
风险高于其余两种模式，安装启用时必须单独显示并批准 `responses:payload`。

产品思路借鉴 warcio 的流式、摘要和 WARC 1.1 方法论；代码与文档均为独立实现。
