# 变更记录

## 0.9.0 — 2026-11-03

迁移到宿主安全边界（重大变更）。插件进程不再直连网络，也不自建浏览器与登录会话：所有 HTTP 请求经宿主 `network.fetch`（`_host_fetch`，遵守宿主 ScopePolicy / robots / 配额），PDF 产物经宿主 `artifact.stream` 交付（`_host_save_pdf`，1 MiB 分块 + commit / abort），本地 workspace 不再写入 PDF 文件；记录改用 `artifact_id` 引用宿主工件，`local_path` 置空。

移除的实现：httpx 直连客户端与代理连接池（`_get_http_client` / `_HTTP_CLIENT` / `_close_http_clients` 等）、Playwright / 机构浏览器登录层、Cookie 读取与落盘（`_save_cookie` 为 no-op，历史 `apd_cookie_*.json` 在设置状态目录时清理）、代理健康探测与代理级重试路由。这些能力改由宿主承担；插件缺宿主 SDK 时拒绝执行对应步骤并记录降级事件（`institutional_login_unsupported`、`proxy_probe_unsupported`、`headed_browser_unsupported`），绝不回退到直连。

下载通道计划收敛为 `oa_direct` + `api`（Crossref / Unpaywall / OpenAlex 镜像优先策略不变）。镜像优先仍取仓储副本（零反爬），出版商 endpoint 仅作后备。机构代理字段在面板保留为只读展示（宿主不应用），不构成能力宣称。权限新增 `artifacts:write`；依赖移除 httpx 与 playwright。

## 0.8.0 — 2026-10-04

保存 canonical_doi、文件 SHA-256 和 download_evidence（渠道、去凭证来源、大小、校验等级、DOI 核验状态、耗时）。原 doi 显示字段保持兼容；规范 DOI 用于输入身份与证据。格式头检查有界读取；安装解析器后结构损坏不会降级冒充解析成功。保存前检查大小；浏览器临时 PDF 按文件路径移入工作区，减少完整文件的内存副本。

allow_weak_pdf_validation: true（默认）允许在无解析器时保留仅格式头匹配的文件，但标记 header_only、verified=false；false 会拒绝并清理。解析器明确报告损坏时始终拒绝。证据中的 URL 去除用户信息、全部查询与片段及已识别的认证路径；本地临时路径不会成为来源 URL。

重试与取消沿用原有策略。PDF 原文仍可能包含用户采集的敏感内容；不声称自动脱敏。XML 下载不属于此版本。
