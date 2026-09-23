# Shopify 公开商品与集合

## 一句话简介
采集仅公开的商品与集合页面；不使用或绕过商店后台接口

## 功能说明
- 采集源：`cms/shopify-public` 站点适配器（市场 ID：`cms/market/shopify-public`）
- 采集方式：HTTP 页面采集（crawl 策略 `crawl`），匹配 `*/collections/*`, `*/products/*`
- 字段抽取：声明式模板（item_path / fields），输出 JSONL / CSV / XLSX
- 礼貌请求：内置请求间延迟，不并发轰炸目标站点

## 适用场景
- 采集 Shopify 商店公开商品与集合信息
- 电商选品与价格监控（仅公开页面）

## 占位符说明
| 占位符 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| collection_url | ✓ | — | 公开集合地址 |

## 兼容性
- `min_core_version: >= 0.11.1`
- `license: OmniCrawler-MIT; 仅采集公开页面; 商品数据权利归各商店所有者`

## 合规与限制
仅采集公开接口/公开页面；如目标站点另有服务条款限制，请自行确认用途合规并保持礼貌频率。

## 使用方式
1. 在 GUI 模板市场安装（信任根验签通过），或 CLI：`omnicrawler templates install cms/market/shopify-public`
2. 新建任务选择本模板，按上表填写占位符
3. 运行后得到结构化输出（JSONL/CSV/XLSX）
