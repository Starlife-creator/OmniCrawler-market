# Academic Paper Downloader（学术论文批量下载器）

从 Web of Science 导出文件（Excel/TSV/RIS/BibTeX/CSV/JSON）批量下载论文 PDF。

## 核心设计

```
能不登录就不登录，能不启动浏览器就不启动浏览器
```

## 三层降级架构

```
Layer 1: OA 直连         → 零认证，直接下载开放获取论文
    ↓ 失败
Layer 2: API 探测        → Crossref / Unpaywall / OpenAlex 获取 OA 链接
    ↓ 失败
Layer 3: 机构代理         → Cookie 预热 → HTTP+Cookie 优先 → 浏览器兜底
    ↓ 失败
    记录失败，跳过该论文
```

## 全优化清单

| 优化项 | 说明 |
|--------|------|
| **并发下载** | 同步信号量（最大 3）接入 `_process`，超限阻塞等待；单域名 Token Bucket 限流 |
| **OpenAlex 批量预检** | seed 阶段批量查所有 DOI 的 OA 状态，减少无效请求 |
| **增量导入** | 大 Excel 分块读取，已下载 DOI 自动跳过 |
| **多格式输入** | 支持 xlsx/xls/tsv/csv/ris/bib/json |
| **编码探测** | WoS 中文系统 GBK 导出自动识别（utf-8-sig→utf-8→gb18030） |
| **智能重试** | 429→3倍退避，5xx→指数退避，网络→中等退避，200-非PDF→按认证失效处理 |
| **反爬识别** | OA 源（auth_method=none）401/403/200-落地页归为 bot_blocked 短重试，不误触发机构重登 |
| **认证自愈** | 机构层 401/403/200-登录墙按出版商分流：订阅源触发重登并用新 Cookie 重试，OA 源识别为反爬不重登 |
| **下载后重命名** | 用 PDF 元数据修正文件名 |
| **批量报告** | hook.after_run 生成 CSV + HTML 看板（含成功论文明细） |
| **代理健康检查** | 代理池预检、熔断器、健康评分 |
| **登录态监控** | 定期检测 Cookie 有效性，失效前刷新 |
| **校园 IP 直连** | campus_ip 模式无需登录 Cookie，无 Cookie 也走浏览器会话；免账号重登 |
| **浏览器内下载** | expect_download 捕获真实会话下载，相对链接绝对化，Cookie 自动补 domain/path，临时文件用后即删 |
| **单次下载** | Layer 1 只构造 URL 不探测、Layer 3 只流式读响应头校验，正文统一由 `_download_with_retry` 下载一次，PDF 绝不下两遍 |
| **分布式锁** | 多实例避免重复下载同一 DOI |
| **配置热重载** | config/publishers.yaml + oa_journals.yaml 可覆盖内置路由表，mtime 变化自动重载，无需重启 |
| **OA 期刊白名单** | ISSN 白名单（config/oa_journals.yaml）+ 预检 + 全 OA 出版商三重信号 |
| **WoS 字段码头** | 官方 TSV 两字母码头（TI/AF/DI/SN…）自动映射为规范列名 |
| **断点续传** | state 记录已完成/失败 DOI，重启自动跳过 |
| **PDF 校验** | 页数>0、非加密、非错误页；解析库不可用时退化为 %PDF 魔数校验，确保最小环境不误删已下载文件 |
| **DOI 交叉核对** | PDF 首页提取 DOI 与请求不一致（出版商发错文件）→ 拒绝并清理，不落盘 |
| **批量崩溃隔离** | 单篇论文内部异常转失败记录，不拖垮批次；分布式锁在崩溃路径下仍释放 |
| **流式下载** | httpx.stream 大文件分块写入 |
| **验证码探测** | 浏览器层探测并上报（OCR 由宿主能力代理，不做宿主 import） |
| **结构化日志** | JSONL 格式含 event/doi/layer/duration_ms |

## 依赖（已声明）

| 依赖 | 许可 |
|------|------|
| httpx ≥0.24 | BSD-3-Clause |
| yaml ≥5.4 | MIT |
| openpyxl ≥3.0 | MIT |
| pdfplumber ≥0.10 | MIT |
| pypdf ≥3.0 | BSD-3-Clause |
| playwright ≥1.30 | Apache-2.0 |

## 配置

### Level 1: OA 用户

```yaml
level: 1
incremental: true
```

### Level 3: 机构代理

```yaml
level: 3
institution:
  proxy_list: ["http://proxy1:8080", "http://proxy2:8080"]
  login_url: "https://login.lib.xxx.edu"
incremental: true
max_per_session: 200
retry_count: 5
retry_base_delay: 2.0
```

### Level 3: 校园直连（无需登录，IP 即授权）

校园网环境下无需代理与登录 Cookie，直接以真浏览器会话下载学校订阅内容：

```yaml
level: 3
campus_ip: true
incremental: true
```

> 浏览器层在真实会话内点击 PDF 链接并捕获下载事件（`expect_download`），
> 不把链接丢回裸 HTTP，避免丢失浏览器会话签名；相对 PDF 链接自动绝对化；
> 手配 Cookie 自动补齐 `url/domain/path` 字段。

## 输出

```
workspace/
├── papers/                    # 下载的 PDF
├── reports/                   # CSV + HTML 报告
│   ├── download_report_2025-09-19_12-00-00.csv
│   └── dashboard_2025-09-19_12-00-00.html
└── ...
```

## 合规声明

- OA 论文下载：完全合法
- 机构代理：使用学校正式代理入口
- 不破解付费墙，不分发下载内容
- 下载速率模拟人类行为
- 代理熔断保护出版商服务器

## 已知限制

- OpenAlex 批量查询每次最多 200 个 DOI
- 并发数建议不超过 3，避免触发风控
- RIS/BibTeX 解析依赖正则，复杂格式可能有偏差
- 分布式锁依赖 state 存储（SQLite），多实例需同一数据库
- 实测 MDPI / RSC 会对脚本化直连返回 403（bot 拦截），需走重试等级或代理
