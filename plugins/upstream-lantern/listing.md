# Upstream Lantern（上游灯塔）

Upstream Lantern 把用户明确填写的 GitHub 公共仓库转换为有限、可审查的只读 API 请求，
用于发现仓库状态、正式发布、Git 标签、提交活动、社区健康度、GitHub Actions 运行状态，
以及与指定软件包相关的 GitHub Reviewed 安全公告。

插件只生成抓取请求，不直接联网，不下载或执行发布附件，不扫描本地依赖，不修改项目，
也不会自动升级、创建 Issue 或提交 PR。

## 适用场景

- 跟踪依赖项目的新版本和发布说明；
- 观察只有标签、没有 GitHub Release 的项目；
- 按时间窗、分支或路径观察公开提交活动；
- 检查项目是否具备 README、许可证、贡献指南和行为准则等社区基础；
- 观察公开仓库最近的 GitHub Actions 工作流是否成功；
- 保存仓库是否归档、默认分支和更新时间等公开元数据；
- 根据明确的软件包名称和生态筛选 GitHub Reviewed 安全公告；
- 配合 OmniCrawler 的定时任务和变更检测生成本地报告。

## 最小配置

```yaml
source:
  kind: upstream-lantern
  seeds:
    - https://api.github.com/repos/Starlife-creator/omnicrawler
  params:
    feeds: [repository, releases]
    per_page: 30
    pages: 1
    max_requests: 100

crawl:
  allow_domains: [api.github.com]
  max_pages: 10
  max_depth: 0

egress:
  allowed_domains: [api.github.com]
```

`seeds` 只接受 HTTPS GitHub 仓库首页、`api.github.com/repos/<owner>/<repo>` 或
`owner/repo`。实际项目配置建议使用 `api.github.com/repos/<owner>/<repo>`，使种子、实际
请求、范围策略和可选凭据域名保持一致。

## 可选 Feed

`source.params.feeds` 支持：

- `repository`：仓库公开元数据；
- `releases`：GitHub Releases，不包含只有 Git tag 的版本；
- `tags`：Git 标签；
- `commits`：提交活动，可按时间、分支或路径缩小范围；
- `community`：社区健康度及 README、许可证、贡献指南等文件的存在状态；
- `workflow_runs`：GitHub Actions 工作流运行状态；
- `advisories`：GitHub Reviewed 全球安全公告，必须同时提供软件包列表。

## 安全预设

普通用户可以用 `preset` 代替手工组合 `feeds`：

- `release`：仓库、发布和标签；
- `maintenance`：仓库、发布、提交、社区健康度和工作流运行；
- `security`：仓库、发布和安全公告，仍必须明确填写 `advisory_packages`；
- `complete`：启用全部 Feed，仍受分页和全局请求预算限制。

最简维护健康配置：

```yaml
source:
  kind: upstream-lantern
  seeds:
    - https://api.github.com/repos/Starlife-creator/omnicrawler
  params:
    preset: maintenance
    max_requests: 20
```

`preset` 与 `feeds` 不能同时配置，避免隐式合并造成请求范围超出用户预期。未填写两者时
仍采用兼容默认值 `repository` 和 `releases`。

提交活动示例：

```yaml
source:
  kind: upstream-lantern
  seeds:
    - https://api.github.com/repos/Starlife-creator/omnicrawler
  params:
    feeds: [repository, releases, commits]
    per_page: 30
    pages: 2
    since: "2026-01-01T00:00:00Z"
    until: "2026-02-01T00:00:00Z"
    sha: main
    path: src/omnicrawler
    max_requests: 20
```

`since` 和 `until` 必须是带时区的 ISO 8601 时间。`sha` 可以是分支或 Git 引用，
`path` 用于把提交结果限制到明确路径。筛选值只会成为经过 URL 编码的查询参数。
这些提交筛选参数只有启用 `commits` 时才允许出现；安全公告包和严重程度参数同样要求启用
`advisories`，避免配置被静默忽略。

安全公告示例：

```yaml
source:
  kind: upstream-lantern
  seeds:
    - https://api.github.com/repos/psf/requests-html
  params:
    feeds: [repository, releases, advisories]
    per_page: 20
    severity: high
    advisory_packages:
      - ecosystem: pip
        name: requests
      - ecosystem: npm
        name: lodash
        version: 4.17.20
```

每个安全公告查询只包含一个明确软件包。支持的生态为 GitHub API 当前公开枚举：
`actions`、`composer`、`erlang`、`go`、`maven`、`npm`、`nuget`、`other`、`pip`、
`pub`、`rubygems`、`rust`、`swift`。

## 请求边界

- 固定目标域名：`api.github.com`；
- 仓库上限：20；
- 安全公告软件包上限：50；
- `per_page` 自动限制为 1 到 100；
- `pages` 自动限制为 1 到 5，只作用于发布、标签和提交 Feed；
- `pages` 同样作用于工作流运行 Feed，社区健康度和安全公告保持单页；
- `max_requests` 自动限制为 1 到 100，计划超出预算时整批拒绝；
- 重复仓库和重复软件包查询会被去重；
- 不接受 HTTP、其他域名、带查询参数的仓库地址或仓库子页面；
- 不接受带端口或用户信息的仓库 URL，错误信息也不会回显原始地址；
- 仓库所有者和仓库名必须是明确的 ASCII 字符串，不把数字或复杂对象隐式转换成地址；
- 请求只使用固定的公开 API 版本头，不携带 Cookie、Token 或用户自定义头。

每个请求都带有稳定的 `lantern_key`、信号类型和只读标记，便于后续提取、去重和审计。
插件采用严格失败关闭：任意仓库、Feed、提交筛选或安全公告参数无效时返回零个请求，避免
用户误以为部分成功代表完整结果。数值越界会收缩到安全上限并给出可见警告。
未知 `source.params` 字段也会失败关闭，且错误信息不会回显字段值，避免拼写错误被静默忽略
或把意外填入的敏感内容带入诊断输出。
Feed、预设、安全公告字段必须使用明确的数据类型；布尔值和小数不会被静默当成分页数字。

插件权限声明为空，因为插件进程自身不调用 `network.fetch`；它只返回
`source.seed` 请求。真正的 HTTP 访问由 OmniCrawler 核心执行，仍受 `crawl.allow_domains`、
`egress.allowed_domains`、robots、响应大小、频率和资源限制控制。

## 认证与速率限制

第一版面向公共资源，无需凭据。GitHub 对未认证请求实施较低的速率限制。如果用户确实需要
认证，应在宿主 `http.headers` 中通过 `secret://` 配置 Authorization，并把
`egress.credential_domains` 明确限制为 `api.github.com`。不要把凭据放在 `source.headers`、
插件目录、日志或分享包中；插件只会收到 `source` 配置，不会读取宿主 `http` 段。

## 数据与许可

- 插件代码：MIT；
- 第三方依赖：无；
- 数据来源：GitHub REST API；
- GitHub 返回的仓库、发布和安全公告内容仍受其原始作者权利、GitHub 条款及适用法律约束；
- 使用者负责确认访问、保存和再分发数据的合法性。

API 参考：

- https://docs.github.com/en/rest/repos/repos#get-a-repository
- https://docs.github.com/en/rest/releases/releases#list-releases
- https://docs.github.com/en/rest/repos/repos#list-repository-tags
- https://docs.github.com/en/rest/commits/commits#list-commits
- https://docs.github.com/en/rest/metrics/community#get-community-profile-metrics
- https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-repository
- https://docs.github.com/en/rest/security-advisories/global-advisories
- https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api
- https://docs.github.com/en/rest/about-the-rest-api/api-versions

## 已知限制

- 只支持 GitHub.com，不支持 GitHub Enterprise 自定义域名；
- 社区健康度接口不适用于 fork 仓库，GitHub 可能返回未找到；
- 私有仓库及其工作流通常需要用户在宿主侧另行配置只读认证；
- 不读取本地锁文件，也不判断当前安装版本是否真正受漏洞影响；
- 只预生成用户明确指定的有限页数，不动态跟随响应中的分页链接；
- 安全公告查询保持单页，避免绕开请求预算或引入游标状态；
- 不把“没有结果”解释为“没有风险”，API 限流、权限和数据延迟都可能造成缺失；
- 插件只负责发现请求，字段提取、保存、定时调度和通知由 OmniCrawler 配置承担。

## 独立实现声明

本插件根据“确定性证据优先、只读监控、失败时不自动修改项目”的方法论独立设计并从空白
代码实现，没有复制借鉴项目的源代码、测试、文档或素材。
