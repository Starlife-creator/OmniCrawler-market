# WordPress 公开文章 REST API

## 一句话简介
使用 WordPress REST API 按页采集公开文章，默认每页 100 条

## 功能说明
- 采集源：`cms/wordpress-rest` 站点适配器（市场 ID：`cms/market/wordpress-rest`）
- 采集方式：HTTP API（站点适配器 `site_wordpress`），匹配 `*/wp-json/wp/v2/*`
- 字段抽取：声明式模板（item_path / fields），输出 JSONL / CSV / XLSX
- 礼貌请求：内置请求间延迟，不并发轰炸目标站点

## 适用场景
- 按页批量采集 WordPress 站点公开文章
- CMS 内容归档与站点迁移前的数据盘点

## 占位符说明
| 占位符 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| site_url | ✓ | — | WordPress 站点根地址 |
| end_page |  | 20 | 最大页码 |

## 兼容性
- `min_core_version: >= 0.11.1`
- `license: OmniCrawler-MIT; API 行为依据 WordPress 官方文档`

## 合规与限制
仅采集公开接口/公开页面；如目标站点另有服务条款限制，请自行确认用途合规并保持礼貌频率。

## 使用方式
1. 在 GUI 模板市场安装（信任根验签通过），或 CLI：`omnicrawler templates install cms/market/wordpress-rest`
2. 新建任务选择本模板，按上表填写占位符
3. 运行后得到结构化输出（JSONL/CSV/XLSX）
