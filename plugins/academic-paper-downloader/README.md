# Academic Paper Downloader

从 Web of Science 导出文件批量下载论文 PDF 的 OmniCrawler 插件。
v0.3.0：全优化版 —— 修复 OpenAlex 预检失效与 publishers.yaml 热重载失效、.xls 优雅兜底、PDF 流式落盘 + 100MB 上限、state 按 DOI 分键、CSV/HTML 注入防护、Layer 2 并发探测、并发等待改条件唤醒。

## 三层降级策略

```
Layer 1: OA 直连         → 零认证，直接下载开放获取论文（OpenAlex 预检标记）
    ↓ 失败
Layer 2: API 探测        → Crossref / Unpaywall / OpenAlex 获取 OA 链接
    ↓ 失败
Layer 3: 机构代理         → HTTP+Cookie 优先，浏览器模拟兜底；认证失效自动重登重试
```

## 快速开始

### Level 1: OA 用户（无需配置）

```bash
# 只需提供导出文件（xlsx/xls/tsv/csv/ris/bib/json）
omnicrawler run --source academic-paper-downloader --file savedrecs.xlsx
```

### Level 2: API 增强

```bash
omnicrawler run --source academic-paper-downloader --file savedrecs.xlsx \
  --config "unpaywall_email=your@email.com"
```

### Level 3: 机构代理

```bash
omnicrawler run --source academic-paper-downloader --file savedrecs.xlsx \
  --config institution.proxy_url=http://proxy.lib.xxx.edu:8080 \
  --config institution.login_url=https://login.lib.xxx.edu
```

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
# 本地单元测试（158 项，含配置接线/WoS GBK/优化回归/真实网络冒烟/反爬分流/DOI 交叉核对）
pytest tests --ignore=tests/test_contract.py

# 契约 2 验收（需 OmniCrawler 核心，在仓库内运行）
pytest -m plugin_contract

# 市场审计零 error
omnicrawler plugin audit .
```
