# community-guide · 官方社区引导

## 1.1.0 开发版（2026-10-03，待作者签名）

缺陷报告、功能建议、Issues 交流、插件投稿、贡献指南和行为准则采用直接入口。不假定 Discussions 当前开放状态；导航保持零网络、零凭据。

以上为当前行为；下文旧版本内容保留为历史说明。


P2.3 外链降级版（§10.9 #21 拍板形态）：仓库未启用 Discussions ⇒ 首版 = 纯静态外链导航面板。

- 零网络（不申请任何网络能力）、零凭据、零 Qt 触碰
- UI 走声明式 `rich_text`（P2.1 组件），外链经宿主确认后由系统浏览器打开
- 仓库启用 Discussions 后可升级为 API 拉取形态（另行拍板）

## 测试

在 OmniCrawler 仓库根：`pytest ../market-plugin-and-template-development/community-guide/tests -q`
