# issue-wishlist · 官方需求清单

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
