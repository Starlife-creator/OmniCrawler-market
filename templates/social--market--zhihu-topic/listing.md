# 知乎话题与问答采集

## 一句话简介
采集知乎话题页面或搜索结果的问题列表，自动提取标题、摘要、回答数、关注数

## 功能说明
- 采集源：`social/zhihu-topic` 站点适配器（市场 ID：`social/market/zhihu-topic`）
- 采集方式：浏览器引擎（`browser`），匹配 `*/topic/*`, `*/search*`, `*/question/*`
- 字段抽取：声明式模板（item_path / fields），输出 JSONL / CSV / XLSX
- 礼貌请求：内置请求间延迟，不并发轰炸目标站点

## 适用场景
- 按话题/搜索采集知乎公开问题列表
- 问答数据的趋势与话题研究

## 占位符说明
| 占位符 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| topic_url | ✓ | — | 知乎话题或搜索页地址 (如 https://www.zhihu.com/topic/12345) |

## 兼容性
- `min_core_version: >= 0.11.1`
- `license: OmniCrawler-MIT; 仅公开内容; 须符合知乎服务条款`

## 合规与限制
本模板仅采集**未登录状态下公开可见**的内容；不提供、也不应被用于绕过登录验证、付费墙或反爬机制。请在使用前自行确认用途符合平台最新服务条款与当地法律法规，并保持礼貌的采集频率（建议降低并发、加长延迟），避免对目标站点造成负担。

## 使用方式
1. 在 GUI 模板市场安装（信任根验签通过），或 CLI：`omnicrawler templates install social/market/zhihu-topic`
2. 新建任务选择本模板，按上表填写占位符
3. 运行后得到结构化输出（JSONL/CSV/XLSX）
