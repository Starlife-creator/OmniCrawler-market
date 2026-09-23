# Discourse 公开话题列表

## 一句话简介
采集 Discourse 公开话题列表及详情 JSON

## 功能说明
- 采集源：`cms/discourse-topics` 站点适配器（市场 ID：`cms/market/discourse-topics`）
- 采集方式：HTTP API（站点适配器 `site_discourse`），匹配 `*/latest.json*`, `*/top.json*`, `*/c/*/*.json*`
- 字段抽取：声明式模板（item_path / fields），输出 JSONL / CSV / XLSX
- 礼貌请求：内置请求间延迟，不并发轰炸目标站点

## 适用场景
- 采集 Discourse 社区公开话题与详情 JSON
- 论坛讨论内容的结构化存档

## 占位符说明
| 占位符 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| site_url | ✓ | — | Discourse 站点根地址 |
| end_page |  | 20 | 最大页码 |

## 兼容性
- `min_core_version: >= 0.11.1`
- `license: OmniCrawler-MIT; API 行为依据 Discourse 官方文档`

## 合规与限制
仅采集公开接口/公开页面；如目标站点另有服务条款限制，请自行确认用途合规并保持礼貌频率。

## 使用方式
1. 在 GUI 模板市场安装（信任根验签通过），或 CLI：`omnicrawler templates install cms/market/discourse-topics`
2. 新建任务选择本模板，按上表填写占位符
3. 运行后得到结构化输出（JSONL/CSV/XLSX）
