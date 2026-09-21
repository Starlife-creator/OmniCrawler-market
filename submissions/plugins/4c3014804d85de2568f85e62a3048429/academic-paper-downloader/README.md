# Academic Paper Downloader

从 Web of Science 导出文件批量下载论文 PDF 的 OmniCrawler 插件。

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
Layer 3: 机构代理         → HTTP+Cookie 优先，浏览器模拟兜底；认证失效自动重登重试
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
