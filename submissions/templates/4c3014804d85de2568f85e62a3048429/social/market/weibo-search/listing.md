# 微博搜索采集

## 一句话简介
采集微博搜索页或话题页的帖子列表，自动提取内容、作者、转发/评论/点赞数据

## 功能说明
- 采集源：`social/weibo-search` 站点适配器（市场 ID：`social/market/weibo-search`）
- 采集方式：浏览器引擎（`browser`），匹配 `*/weibo*`, `*/s.weibo.com/*`
- 字段抽取：声明式模板（item_path / fields），输出 JSONL / CSV / XLSX
- 礼貌请求：内置请求间延迟，不并发轰炸目标站点

## 适用场景
- 按关键词/话题采集微博公开帖子
- 舆情监控与热点追踪

## 占位符说明
| 占位符 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| search_url | ✓ | — | 微博搜索页地址 (如 https://s.weibo.com/weibo?q=keyword) |

## 兼容性
- `min_core_version: >= 0.11.1`
- `license: OmniCrawler-MIT; 仅公开内容; 须符合微博服务条款`

## 合规与限制
本模板仅采集**未登录状态下公开可见**的内容；不提供、也不应被用于绕过登录验证、付费墙或反爬机制。请在使用前自行确认用途符合平台最新服务条款与当地法律法规，并保持礼貌的采集频率（建议降低并发、加长延迟），避免对目标站点造成负担。

## 使用方式
1. 在 GUI 模板市场安装（信任根验签通过），或 CLI：`omnicrawler templates install social/market/weibo-search`
2. 新建任务选择本模板，按上表填写占位符
3. 运行后得到结构化输出（JSONL/CSV/XLSX）
