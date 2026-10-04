# issue-wishlist（issue-wishlist）

版本：1.2.0 · 更新时间排序与用户标记 · 2026-10-04。发行包使用现有作者身份签名；修改载荷后必须重新签名。

## 功能

保留每条 issue 的 created_at/updated_at，按最近更新或创建排序。支持收藏、已读、收藏列表与未读筛选，刷新失败保留旧列表。

## 配置与状态

新增 state:read/state:write 用于按仓库与 issue 编号保存布尔标记，schema 1，最多 1000 项，超限淘汰最早标记。不可用时仅保留会话标记并明确提示。状态不存 issue 正文、凭据或本机路径。

## 权限与数据去向

声明权限：network:scoped, state:read, state:write。network:scoped 仅访问 api.github.com 公开只读接口，仍只查询开放 Issues；不投票、不评论、不创建远端条目。无自动轮询；30 秒刷新间隔、403/429 至少等待 60 秒。

## 兼容与许可

最低核心版本：0.14.0；执行模式：subprocess；许可：MIT。

## 历史使用参考

以下保留此前版本使用说明；旧版权限、版本和行为描述仅作历史参考，当前行为以本文上方说明为准。

# issue-wishlist · 官方需求清单

## 1.1.0 开发版（2026-10-03，待作者签名）

刷新失败保留旧列表与最后成功时间；刷新间隔 30 秒，403/429 至少等待 60 秒。每次最多 5 页、每页 30 条，过滤 PR 后展示 Issues，达到页数上限明确提示结果可能不完整。支持标题/编号搜索、标签筛选；点击条目后提供受宿主确认的 GitHub 链接。

以上为当前行为；下文旧版本内容保留为历史说明。


OmniCrawler 市场官方 `view` 插件：只读浏览仓库开放 Issues。

- 数据经宿主 `network.fetch`（egress 策略 + 日配额约束、密钥零暴露）
- UI 全部走声明式视图（`rich_text` + `resource_list`），插件不触碰 Qt
- 只读：不登录、不评论、不写远端；`min_core_version >= 0.14.0`（需要 `view.richtext`）

## 开发

```
tests/test_contract.py        # Contract2Suite 契约套件
tests/test_issue_wishlist.py  # 行为测试（stub omnicrawler_sdk）
```

运行：在 OmniCrawler 仓库根 `pytest ../market-plugin-and-template-development/issue-wishlist/tests -q`

## 投稿

维护者驱动脚本（口令走环境变量 `OMNICRAWL_IDENTITY_PASSWORD`）：
`OmniCrawler/.audit-tmp/p22_submit.py`
