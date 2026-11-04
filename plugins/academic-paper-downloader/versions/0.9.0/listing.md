# Academic Paper Downloader（academic-paper-downloader）

版本：0.9.0 · 宿主网络/产物迁移 · 2026-11-03。发行包使用现有作者身份签名；修改载荷后必须重新签名。

## 功能

批量从 Web of Science 导出文件解析 DOI，经 OA 直连与学术 API（Crossref / Unpaywall / OpenAlex）探测获取 PDF，校验后交付。0.9.0 起网络请求与产物交付全部经宿主：HTTP 走宿主 `network.fetch`（遵守宿主 ScopePolicy / robots / 配额），PDF 经宿主 `artifact.stream` 分块写入并提交，本地 workspace 不再保存 PDF 文件，记录以 `artifact_id` 引用宿主工件。

DOI 交叉核对为强校验：请求了 DOI 但 PDF 中提不到 DOI ⇒ 标记未核验（反爬挑战页 / 登录页都提不到 DOI）；提取到但与请求不一致 ⇒ 拒绝并清理。证据字段记录渠道、去凭证来源、大小、校验等级、DOI 核验状态与耗时；URL 去除用户信息、查询与片段。

## 配置与状态

allow_weak_pdf_validation: true（默认）允许在无解析器时保留仅格式头匹配的文件，但标记 header_only、verified=false；false 会拒绝并清理。解析器明确报告损坏时始终拒绝。重试与取消沿用原有策略。PDF 原文仍可能包含用户采集的敏感内容；不声称自动脱敏。XML 下载不属于此版本。

机构代理配置在面板保留为只读展示：宿主 `network.fetch` 不应用代理，下载一律经宿主 EgressBroker，插件不做代理健康探测或代理级重试路由。

## 降级能力（0.9.0 明确不支持）

宿主 SDK 不提供对应能力时，插件拒绝执行并记录事件，不回退到直连或自建浏览器：机构登录（宿主无交互浏览器 / 登录会话能力，Cookie 不存储、不落盘）、代理探测（宿主不暴露代理参数）、无头浏览器通道（宿主无浏览器执行能力）。缺宿主 SDK 时对应步骤抛错由调用方分类，绝不静默成功。

## 权限与数据去向

声明权限：network:scoped, records:read, state:read, state:write, secrets:read, files:read, artifacts:write。网络目标限于声明的出版商与学术 API 域名；产物由宿主管控（大小上限、命名、审计）。Cookie 属会话凭证，插件不写入任何文件。

## 兼容与许可

最低核心版本：0.11.2；执行模式：subprocess；许可：MIT。
