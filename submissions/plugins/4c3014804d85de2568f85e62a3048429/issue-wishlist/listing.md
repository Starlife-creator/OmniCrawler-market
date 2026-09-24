# 官方需求清单（issue-wishlist）

## 一句话简介
只读浏览 OmniCrawler 仓库的开放 Issues——Roadmap 与需求讨论一屏可见，不持任何凭据。

## 功能说明
- 数据源：GitHub 公开 API（`api.github.com`，只读、无认证），经宿主 `network.fetch` 出站代理（egress 策略与日配额约束）
- UI：宿主声明式视图渲染（`rich_text` 说明段 + `resource_list` 条目列表 + 刷新按钮），插件不触碰任何 Qt 对象
- 只读：应用内不登录、不评论、不写任何远端状态；发言请在确认链接后到仓库 Discussions
- 更新：手动「刷新」按钮触发，无后台轮询、无遥测

## 适用场景
- 查看 Roadmap 与进行中的需求
- 挑选想催的 Issue 再去仓库 +1（链接一键可见）
- 离线/配额受限时仍可浏览上次刷新结果

## 占位符说明
本插件无需配置，安装即用；「刷新」按钮按需拉取。

## 兼容性
- `min_core_version: >= 0.14.0`（需要核心的 `view.richtext` 能力；更早版本会在安装后加载阶段明确拒载，不会半装）
- `license: MIT`

## 合规与限制
仅调用 GitHub 公开只读 API；不使用任何认证凭据，不读取或上传本地数据。受宿主出站策略（egress policy）与每日配额约束，可能因网络或配额而刷新失败（面板内会明确提示）。GitHub 服务条款与速率限制以平台为准。

## 使用方式
1. 在 GUI 插件市场安装（信任根验签通过），或 CLI：`omnicrawler plugins install issue-wishlist`
2. 打开「需求清单」面板，点「刷新」
3. 点击条目查看对应 Issue 链接
