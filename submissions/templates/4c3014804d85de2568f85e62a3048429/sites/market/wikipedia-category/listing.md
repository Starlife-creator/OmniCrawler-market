# Wikipedia 分类成员

## 一句话简介
使用 MediaWiki 官方 Action API 采集 Wikipedia 分类成员

## 功能说明
- 采集源：`sites/wikipedia-category` 站点适配器（市场 ID：`sites/market/wikipedia-category`）
- 采集方式：HTTP API（站点适配器 `site_mediawiki`），匹配 `—`
- 字段抽取：声明式模板（item_path / fields），输出 JSONL / CSV / XLSX
- 礼貌请求：内置请求间延迟，不并发轰炸目标站点

## 适用场景
- 采集 Wikipedia 分类的成员页面清单
- 按主题建立词条目录数据集

## 占位符说明
| 占位符 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| language |  | zh | 语言子域 |
| category_name | ✓ | — | 分类名称 |

## 兼容性
- `min_core_version: >= 0.11.1`
- `license: OmniCrawler-MIT; API 行为依据 MediaWiki 官方文档; 内容遵循各站点许可（如 CC BY-SA）`

## 合规与限制
仅采集公开接口/公开页面；如目标站点另有服务条款限制，请自行确认用途合规并保持礼貌频率。

## 使用方式
1. 在 GUI 模板市场安装（信任根验签通过），或 CLI：`omnicrawler templates install sites/market/wikipedia-category`
2. 新建任务选择本模板，按上表填写占位符
3. 运行后得到结构化输出（JSONL/CSV/XLSX）
