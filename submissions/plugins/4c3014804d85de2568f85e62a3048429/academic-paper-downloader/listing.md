# Academic Paper Downloader（academic-paper-downloader）

版本：0.8.0 · 下载来源与校验等级 · 2026-10-04。发行包使用现有作者身份签名；修改载荷后必须重新签名。

## 功能

保存 canonical_doi、文件 SHA-256 和 download_evidence（渠道、去凭证来源、大小、校验等级、DOI 核验状态、耗时）。原 doi 显示字段保持兼容；规范 DOI 用于输入身份与证据。格式头检查有界读取；安装解析器后结构损坏不会降级冒充解析成功。保存前检查大小；浏览器临时 PDF 按文件路径移入工作区，减少完整文件的内存副本。

## 配置与状态

allow_weak_pdf_validation: true（默认）允许在无解析器时保留仅格式头匹配的文件，但标记 header_only、verified=false；false 会拒绝并清理。解析器明确报告损坏时始终拒绝。证据中的 URL 去除用户信息、全部查询与片段及已识别的认证路径；本地临时路径不会成为来源 URL。

## 权限与数据去向

声明权限：network:scoped, records:read, state:read, state:write, secrets:read, files:read。重试与取消沿用原有策略。PDF 原文仍可能包含用户采集的敏感内容；不声称自动脱敏。XML 下载不属于此版本。

## 兼容与许可

最低核心版本：0.11.2；执行模式：subprocess；许可：MIT。
