# Academic Paper Downloader

从 Web of Science 导出文件批量下载论文 PDF 的 OmniCrawler 插件。

v0.6.3：**实机回归修正 + 有头触发收紧（用户定案）** ——
① **浏览器失败原因分类**：`_browser_attempt` 把失败原因写入线程局部
（blocked=挑战页需要人 / no_evidence=页面加载但无 PDF 证据 / navigation_failed）；
编排层把 blocked 上报为 `bot_blocked`——修复"挑战页信号被浏览器静默失败抹掉、
有头轮永远抓不到目标"的缺陷（实机 50 篇回归发现：21 篇被拦但 error_class 全为 unknown）。
② **有头触发收紧**：有头轮目标仅 bot_blocked/captcha（需要人机验证的失败）；
auth_required（纯订阅墙）走无头重试 + Cookie/域画像，不弹窗。
③ **无头指纹优化**：隐藏 `navigator.webdriver`、真实 locale/时区/chrome 对象——
降低无头被识别概率，从源头减少"需要有头"的场景。

v0.6.2：**接入宿主 v528cedc 面板能力（U4/U6 插件侧收口）** ——
① **text 输入组件**：面板"机构代理 / 登录页"改为可编辑输入框（configure-proxy /
configure-login-url action，值经 view.action payload.value 上送，maxlength 512），
GUI 用户自由填写代理与登录页，"打开登录窗口"直接使用面板填写的登录页；
② **view.progress 进度上报**：每篇论文结束时 `omnicrawler_sdk.call("view.progress",
{done,total,current_doi,eta_seconds,success,failed})`（字段面与 broker 白名单一致），
面板进度条实时刷新；每篇一次兼任 drive_loop 会话保活（宿主每读到一行输出重置会话超时）；
独立运行（无 SDK）静默 no-op。宿主侧改动见 commit 528cedc。

v0.6.1：**重试执行器统一（D4）+ 面板代理选择（U4 部分）** ——
① `_rerun_failed`/`_merge_retry` 统一失败重试执行器：代理补填、有头第二阶段、面板代理重试
三个入口共用同一"重建元数据 → 逐篇执行 → 合并结果"循环，失败记录标准化（含 retryable/
first_author/year），消除双份逻辑漂移；② 面板新增"机构代理"下拉（任务配置含 proxy_list 时
出现），GUI 用户选择后 `_after_run` 的失败重试自动使用该代理——不开命令行也能补代理；
③ 选择代理即写入 view 配置并同步 Cookie 键对齐。

v0.6.0：**分析清单全量收口** ——
① `defer_headed` 默认开启（两阶段为推荐形态；显式传 false 恢复批内即时弹窗）；
② `bot_blocked`/`captcha` 不再退避重试（通道不变重试无意义，时间让给通道升级）；
③ **域级通道画像**：出版商域发生 bot_blocked/captcha 后 30 分钟冷却期内，同域论文跳过
http 通道直接走浏览器升级（画像即升级证据）；
④ **通道计划数据驱动**（D6）：编排降为"通道列表 + 运行时门控"的通用循环，新增通道不改编排；
⑤ **失败分类细化**（D11）：`unknown_publisher` 显式归类、失败记录带 `retryable` 标记、
冗余 first_author/year 保证文件移动后重试命名正确（U7）；
⑥ **无 DOI 行显式计数**（U3）入 meta + warning；未填 `unpaywall_email` 时输出提示（U2）；
⑦ dashboard：失败按 error_class 分组小计 + 全部/仅成功/仅失败筛选（零依赖）；
⑧ 状态文件版本化（D7，`{"v":1,"value":...}`，兼容旧格式）；调优写入收敛为
`_apply_runtime_tuning` 单一入口（D3）；8 处裸 `except pass` 补 DEBUG 观测（D2）；
⑨ D1 定案：市场打包要求单文件 plugin.py + 单文件签名，不拆分，按分区注释纪律维护。
测试 209 项 + 契约 6 项全过。

v0.5.0：**工作台 view 面板「登录中心」** —— 插件新增 `view` 形态，出现在工作台侧边面板：
登录态状态（有效/失效/无）、登录页地址、消息区，以及三个按钮——**打开登录窗口**（后台线程
弹出独立有头 Chromium，用户在窗口内直接完成登录与人机验证，Cookie 自动捕获入库并在后续
下载中复用，不重复登录）、**清除登录态**、**刷新状态**。生命周期与异常：后台线程不阻塞
面板、重复点击提示进行中、页面加载失败/超时在消息区显示原因、Cookie 失效引导重登；
Cookie 只经 SDK state 存取，永不落 workspace 明文。任务运行时会自动把
`institution.login_url/proxy_url` 同步给面板（Cookie 键按代理设置对齐）。
说明：宿主 view 契约为声明式控件面板，不含浏览器引擎，故"面板内嵌网页"不可行，
采用"面板 + 独立有头浏览器窗口"组合实现同等体验。

v0.4.0：**反爬横切 + 通道轴架构落地** ——
① **通道升级**：`bot_blocked`/`captcha` 不再是终态失败，而是"通道不匹配"信号（按累计判定，
不被后续层覆盖），OA 内容（L1/L2）同样允许走浏览器通道重试，不再限于机构内容；
② **镜像优先**：Unpaywall 探测优先取仓储副本（arXiv/PMC/机构库，零反爬），出版商链接后备；
③ **有头重试串行化**：并发下最多同时弹一个可见浏览器窗口（`_HEADED_LOCK`）；
④ **两阶段批处理**（`defer_headed`，默认关）：批内抑制可见浏览器弹窗，报告生成前对
bot_blocked/captcha 失败集中走一轮串行有头（`headed_deferred`）；
⑤ **增量状态文件兜底**：宿主 SDK 缺席（独立运行）时，done/failed 状态落
`<workspace>/.apd_state/`，消除重复下载；Cookie 永不落文件（会话凭证）；
⑥ **robots.txt 按域缓存**：每域进程内只请求一次；
⑦ **登录 Cookie 捕获时机修复**：旧 `wait_for_url("**/*")` 瞬间匹配、不等用户完成登录，
现轮询等待页面离开登录域（最多 120s）。

v0.3.3：**校外场景的代理补填与失败重试** —— 新增 `retry_prompt_proxy` 配置（默认关闭）：
开启后，批处理结束、最终报告生成之前，若存在失败文献且尚未配置代理，插件会在控制台
停留一次，让用户填写机构代理 `proxy_url` / 登录页 `login_url`（直接回车 = 明确跳过），
填写后自动用新配置重试全部失败文献（成功者并入成功列表，仍失败者以最新原因覆盖），
然后才生成最终报告。非交互环境（GUI 宿主/重定向 stdin/EOF/Ctrl-C）静默跳过，绝不中断。
同时修复：`_get_http_client` 现在把 `institution.proxy_url` 接入 httpx 客户端
（此前代理只对浏览器通道生效，HTTP 层无视代理），代理切换时自动重建连接池。

v0.3.2：**全自动机构下载（去掉校园网前置门槛）** —— 旧版 Level 3 要求先配置 `proxy_url`/`login_url`/
`campus_ip` 之一，且运行时还有 `(cookies_raw or campus_direct)` 二道门，否则机构层连试都不试。
现在：**直接用当前网络尝试，结果判定** —— 在校园网 → IP 授权成功；普通网络 → 失败并记录
`error_class` + 人类可读 `reason`（网络不可达/超时/无权限/反爬拦截等）后继续队列，全程无人工确认、
不中断等待。失败汇总进最终报告（CSV Message 列 = `error_class@layer: reason`；HTML 看板失败表
新增 title / error_class@layer / reason 三列）。`_mark_failed` 记录扩展为
`{doi, title, layer, error_class, reason, time}`。

v0.3.1：**修掉"假成功"** —— 反爬挑战页/登录页/文章落地页都可能被 `page.pdf()` 打成"合法的 1 页 PDF"并被
计入成功；同一批里 DOI 交叉核对还是**条件性**的（提不到 DOI 就直接放行）。现在：页面命中反爬/登录特征
直接放弃、`page.pdf()` 兜底必须**有"这就是 PDF"的证据**、请求了 DOI 却提不出 DOI 一律判为失败。
另外：浏览器层统一经 `doi.org` 解析到实际文章页（不再假设各家都有 `/doi/<doi>` 入口）、`institution.headless`
可配且被挑战时用可见浏览器重试一次、补 10 个常见 DOI 前缀、未知出版商也走一次通用路径。

## 三层降级策略

```
Layer 1: OA 直连         → 零认证，直接下载开放获取论文（OpenAlex 预检标记）
    ↓ 失败
Layer 2: API 探测        → Crossref / Unpaywall / OpenAlex 获取 OA 链接
    ↓ 失败
Layer 3: 机构通道         → HTTP+Cookie 优先，浏览器模拟兜底；认证失效自动重登重试
                           （v0.3.2 起无需任何前置配置：直接尝试，结果判定是否在校内网络）
```

## 快速开始

本插件是**文件型 source 插件**：入口是导出文件，不是种子 URL。核心 `run` 只接受 `-c <任务配置>`，
没有 `--source/--file` 这类命令行开关 —— 入口写在任务配置里（`source.kind` + `source.file`）。

### Level 1: OA 用户（无需配置）

```yaml
# task.yaml
project:
  name: wos-batch
source:
  kind: academic-paper-downloader
  file: savedrecs.xlsx        # 相对运行工作区；xlsx/xls/tsv/csv/ris/bib/json
  level: 1
```

```bash
omnicrawler run -c task.yaml
```

### Level 2: API 增强（Unpaywall 邮箱）

```yaml
source:
  kind: academic-paper-downloader
  file: savedrecs.xlsx
  level: 2
  unpaywall_email: your@email.com
```

### Level 3: 机构访问（代理 / 校园 IP）

```yaml
source:
  kind: academic-paper-downloader
  file: savedrecs.xlsx
  level: 3
  institution:
    proxy_url: http://proxy.lib.xxx.edu:8080
    login_url: https://login.lib.xxx.edu
    headless: true            # 可配；被反爬挡下时会用可见浏览器重试一次
```

> 校园 IP 直连（`campus_ip: true`）时无需 `proxy_url` / `login_url`。

### GUI

插件市场安装后，在任务画布把 source 选为 `academic-paper-downloader` 并选择输入文件即可。

## 输出

```
workspace/
├── papers/                     # 下载的 PDF（下载后按元数据重命名）
├── reports/
│   ├── download_report_<ts>.csv
│   └── dashboard_<ts>.html     # 成功/失败汇总看板
```

## 合规说明

- OA 论文下载：完全合法
- 机构代理下载：使用学校正式代理入口，用户有订阅权限
- 不破解付费墙，不分发下载内容，仅限个人学术使用
- 并发上限 3 + 单域名限流：下载速率模拟人类行为，避免对出版商服务器造成压力

## 验证

```bash
# 本地单元测试（含配置接线/WoS GBK/优化回归/真实网络冒烟/反爬分流/DOI 交叉核对）
pytest tests --ignore=tests/test_contract.py

# 契约 2 验收（需 OmniCrawler 核心，在仓库内运行）
pytest -m plugin_contract

# 市场审计零 error
omnicrawler plugin audit .
```
