# Drupal JSON:API 内容

## 一句话简介
使用 Drupal 核心 JSON:API 采集公开内容，并处理 links.next 分页

## 功能说明
- 采集源：`cms/drupal-jsonapi` 站点适配器（市场 ID：`cms/market/drupal-jsonapi`）
- 采集方式：HTTP API（站点适配器 `site_drupal`），匹配 `*/jsonapi/*`
- 字段抽取：声明式模板（item_path / fields），输出 JSONL / CSV / XLSX
- 礼貌请求：内置请求间延迟，不并发轰炸目标站点

## 适用场景
- 采集 Drupal 站点公开内容（JSON:API）
- 政府/机构类 Drupal 站点的内容监控

## 占位符说明
| 占位符 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| site_url | ✓ | — | Drupal 站点根地址 |
| content_type |  | article | 内容类型机器名 |

## 兼容性
- `min_core_version: >= 0.11.1`
- `license: OmniCrawler-MIT; API 行为依据 Drupal 官方文档`

## 合规与限制
仅采集公开接口/公开页面；如目标站点另有服务条款限制，请自行确认用途合规并保持礼貌频率。

## 使用方式
1. 在 GUI 模板市场安装（信任根验签通过），或 CLI：`omnicrawler templates install cms/market/drupal-jsonapi`
2. 新建任务选择本模板，按上表填写占位符
3. 运行后得到结构化输出（JSONL/CSV/XLSX）
