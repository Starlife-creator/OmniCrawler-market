# 贡献指南（OmniCrawler 插件生态）

欢迎向 OmniCrawler 插件生态提交内容。本仓库采用 **git-as-registry** 模式：
提交 PR 合并即上架。请阅读本指南与 `README.md`、`CATALOG_SCHEMA.md` 后提交。

## 可提交的内容

| 内容 | 存放位置 | 说明 |
|------|----------|------|
| 插件 | `plugins/<plugin_id>/` | plugin.py + plugin.py.sig + listing.md + plugin.yaml |
| 模板 | `templates/<market_id>/` | template.yaml + template.yaml.sig + listing.md（+ 可选 creator.sig/identity） |
| 作者身份 | `authors/<username>.yaml` | 首次发布前必须提交 |

## 提交一个新插件（完整流程）

1. 在 `plugins/` 下新建 `<plugin_id>/` 目录。
2. 放入 `plugin.py`（含 `def register(registry)`）与强制的 `listing.md`。
3. 新建 `plugin.yaml` 清单；`publisher` 与 `author_fingerprint` 必须在
   `authors/` 中有对应记录。
4. 通过插件契约测试（主仓库 `tests/unit/plugin/`）。
5. 运行 `python tools/generate_catalog.py` 重新生成 `catalog.json`。
6. 提交 PR。**所有提交必须 `git commit --signoff`（DCO）**。

> 签名流程（签名工具 `sign_plugin.py` 位于**主仓库** `OmniCrawler/tools/`，
> 从本仓库根执行时用 `../OmniCrawler/tools/...` 引用）：
> 1. **创作者签名（创建即签名，插件可选）**：创作者用本地身份签名，生成
>    `creator.sig` + `creator.identity`（可过生成器完整性校验进入目录）：
>    `python ../OmniCrawler/tools/sign_plugin.py creator-sign plugins/<id>/ --username <你的用户名>`
> 2. **市场分发签名**：**模板必经**——PR 审核通过后、合并前，由持有信任根
>    冷私钥的维护者签名（下载端/CI 校验的唯一签名）：
>    `python ../OmniCrawler/tools/sign_plugin.py sign templates/<id>/template.yaml --private-key <冷存储私钥>`
>    **插件二选一**：已附创作者轨即可过校验入库待审；但应用端对市场来源
>    插件只认维护者签名（未冷签在用户端会被拒载），故对外分发的插件
>    实际仍需维护者在合并前冷签：
>    `python ../OmniCrawler/tools/sign_plugin.py sign plugins/<id>/plugin.py --private-key <冷存储私钥>`
> 3. **市场分发签名统一用 `plugin.py.sig`**（由 `sign` 生成并覆盖）；旧版 `maintainer-sign`
>    命令已删除，其产物 `maintainer.sig` 不再产生、验证器也不兼容。信任根签名即背书。

## 三层信任模型

| 层级 | 签名 | 用户行为 | 加载策略 |
|------|------|----------|----------|
| 1 | `template.yaml.sig` / `plugin.py.sig`（信任根验签） | 无需操作 | 直接加载（自动信任） |
| 2 | `creator.sig` + 指纹在信任列表 | 首次使用已授权 | 直接加载 |
| 2b | `creator.sig` + 未信任 | 弹出信任提示 | 信任则加载，否则拒绝 |
| 3 | 无签名 | — | 拒绝加载（配置信任根时） |

> **B02-005 限定**：本表对插件与模板的**分发路径规则不同**——**模板强制要求
> 维护者冷密钥签名**（`template.yaml.sig`，CI 拒无签名模板），层级 2/2b 的
> 「仅创作者签名」只在 **P2P 分发**时成立，市场分发路径上不适用。插件则允许
> 维护者轨或创作者轨二者有一即可。

## CI 门禁（合并前自动执行）

- `tools/generate_catalog.py --check`：
  - plugin.yaml 必填字段齐全、id 合法、无未知字段；
  - `catalog.json` 与 YAML 源完全一致（禁止手改派生物）；
  - `author_fingerprint` 与 `authors/` 记录及公钥实际指纹相符；
  - 插件文件存在；
  - 签名文件可通过信任根验签（已签名条目）。
- 拆库演练：复制本目录（`tools/` 等）至临时目录后可独立校验。

## 作者身份（用户名与指纹）

- `username` 是本地唯一标识，文件名 = username。
- `fingerprint`（公钥 SHA-256 前 16 字节 hex）是生态中**绝对唯一标识**。
- 显示名冲突：同名用户的后缀（`-01`、`-02`…）由 CI 校验连续性，先注册者保持原名。

## 安全要求

- 私钥绝不入库：`.gitignore` 已按 glob 拦截 `*.pem`（仅 `keys/plugin_trust.pub.pem`
  公钥例外放行）、`.env`、`*.key` 等。
- 提交前请运行 `python tools/scan_plugin.py scan plugins/<plugin_id>/` 做发布前安全扫描。
- 插件只应声明运行所需的最小权限（`permissions` 字段）。

## 模板数据来源条款（站点类模板准入标准）

采集第三方平台数据的**站点类模板**，发布者必须在 `listing.md` 与 `template.yaml` 中声明数据来源条款：

- 数据来自哪个平台 / API，受何种服务条款约束；
- 是否需 API Key、匿名可用额度与速率限制；
- 礼貌参数（如 Crossref 的 `mailto`、GitHub 的 2s 延迟）与用量预算。

未声明数据来源条款的站点类模板，维护者审核时**不予合并**（合规风险前置拦截）。

## 行为准则

所有贡献者须遵守 `CODE_OF_CONDUCT.md`（Contributor Covenant 2.1）。
