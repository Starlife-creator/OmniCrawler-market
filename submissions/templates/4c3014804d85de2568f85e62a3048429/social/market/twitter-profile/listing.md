# Twitter/X 用户主页采集

## 一句话简介
采集指定 Twitter/X 用户主页的推文时间线，自动提取推文及互动数据

## 功能说明
- 采集源：`social/twitter-profile` 站点适配器（市场 ID：`social/market/twitter-profile`）
- 采集方式：浏览器引擎（`browser`），匹配 `*twitter.com/*`, `*x.com/*`
- 字段抽取：声明式模板（item_path / fields），输出 JSONL / CSV / XLSX
- 礼貌请求：内置请求间延迟，不并发轰炸目标站点

## 适用场景
- 采集指定用户的公开推文时间线
- 账号动态追踪与社交媒体研究

## 占位符说明
| 占位符 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| profile_url | ✓ | — | Twitter 用户主页地址 (如 https://twitter.com/username) |

## 兼容性
- `min_core_version: >= 0.11.1`
- `license: OmniCrawler-MIT; 仅公开内容; 须符合 X/Twitter 服务条款`

## 合规与限制
本模板仅采集**未登录状态下公开可见**的内容；不提供、也不应被用于绕过登录验证、付费墙或反爬机制。请在使用前自行确认用途符合平台最新服务条款与当地法律法规，并保持礼貌的采集频率（建议降低并发、加长延迟），避免对目标站点造成负担。

## 使用方式
1. 在 GUI 模板市场安装（信任根验签通过），或 CLI：`omnicrawler templates install social/market/twitter-profile`
2. 新建任务选择本模板，按上表填写占位符
3. 运行后得到结构化输出（JSONL/CSV/XLSX）
