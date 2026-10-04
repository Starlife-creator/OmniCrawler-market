# 变更记录

## 0.4.0 — 2026-10-04

分别统计 scanned_inputs、业务 records、missing_payloads、truncated_payloads。输出输入上限、是否仍有后续数据及终止原因；同一 WARC 增加 metadata 索引记录，关联 Record-ID、来源、载荷摘要和截断状态。

mode: privacy / metadata / preservation；max_records 默认 1000，最多 5000。summary.records 为业务记录数，system_records=1 为索引记录。索引与正文合计受 25 MiB 未压缩限制，超限会 abort，不提交半套产物。

privacy/metadata 索引随正文脱敏；preservation 明确保留响应正文，属于 body-only resource，不是完整 HTTP 响应或动态页面离线镜像。正文获取异常中止并 abort；缺失引用或无效 base64 计为 missing_payloads。
