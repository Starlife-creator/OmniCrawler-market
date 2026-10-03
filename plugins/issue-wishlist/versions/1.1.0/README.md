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
