## 变更摘要

说明本次提交的插件/模板变更。

## 变更类型

- [ ] 新增插件
- [ ] 更新插件（版本升级）
- [ ] 撤回插件（附安全公告链接）
- [ ] 新增模板
- [ ] 更新模板
- [ ] 作者身份（authors/）变更

## 插件/模板信息

- ID：`<id>`
- 版本：`<x.y.z>`
- 发布者：`<username>`
- 作者公钥指纹：`<fingerprint>`

## 检查清单（CI 自动复核项 + 人工核对项）

CI 自动复核：

- [ ] `plugin.yaml` 字段完整且无未知字段
- [ ] `catalog.json` 已用 `tools/generate_catalog.py` 重新生成
- [ ] `authors/` 中已存在本发布者的身份记录（首次发布）

人工核对（CI 无对应门禁，请逐项确认）：

- [ ] `plugin.py` 含 `def register(registry)`（若为插件）
- [ ] `listing.md` 已填写（功能、权限、兼容、作者、版本、许可）
- [ ] 所有提交已 `git commit --signoff`（DCO）

## 权限声明

列出插件声明的 `permissions` 及理由（最小权限原则）。

## 相关说明

（可选）实现细节、测试情况、兼容性说明。
