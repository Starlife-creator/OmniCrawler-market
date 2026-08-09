# 贡献指南（OmniCrawler 插件生态）

欢迎向 OmniCrawler 插件生态提交内容。本仓库采用 **git-as-registry** 模式：
提交 PR 合并即上架。请阅读本指南与 `README.md`、`CATALOG_SCHEMA.md` 后提交。

## 可提交的内容

| 内容 | 存放位置 | 说明 |
|------|----------|------|
| 插件 | `plugins/<plugin_id>/` | plugin.py + plugin.py.sig + listing.md + plugin.yaml |
| 作者身份 | `authors/<username>.yaml` | 首次发布前必须提交 |

## 提交一个新插件（完整流程）

1. 在 `plugins/` 下新建 `<plugin_id>/` 目录。
2. 放入 `plugin.py`（含 `def register(registry)`）与强制的 `listing.md`。
3. 新建 `plugin.yaml` 清单；`publisher` 与 `author_fingerprint` 必须在
   `authors/` 中有对应记录。
4. 通过插件契约测试（主仓库 `tests/unit/plugin/`）。
5. 运行 `python tools/generate_catalog.py` 重新生成 `catalog.json`。
6. 提交 PR。**所有提交必须 `git commit --signoff`（DCO）**。

> 签名流程（两步签名）：
> 1. **创作者签名（创建即签名）**：创作者用本地身份签名，生成
>    `creator.sig` + `creator.identity`（三件套之二，P2P 分发可用）：
>    `python tools/sign_plugin.py creator-sign plugins/<id>/ --username <你的用户名>`
> 2. **维护者签名（市场分发）**：PR 审核合并后，由持有冷私钥的维护者在离线机器
>    生成 `maintainer.sig`（仅市场分发携带，用户下载后自动信任）：
>    `python tools/sign_plugin.py maintainer-sign plugins/<id>/ --private-key <冷存储私钥>`
> 3. 创作者无法自签维护者签名；签名即背书。

## 三层信任模型

| 层级 | 签名 | 用户行为 | 加载策略 |
|------|------|----------|----------|
| 1 | `maintainer.sig`（信任根验签） | 无需操作 | 直接加载（自动信任） |
| 2 | `creator.sig` + 指纹在信任列表 | 首次使用已授权 | 直接加载 |
| 2b | `creator.sig` + 未信任 | 弹出信任提示 | 信任则加载，否则拒绝 |
| 3 | 无签名 | — | 拒绝加载（配置信任根时） |

## CI 门禁（合并前自动执行）

- `registry/tools/generate_catalog.py --check`：
  - plugin.yaml 必填字段齐全、id 合法、无未知字段；
  - `catalog.json` 与 YAML 源完全一致（禁止手改派生物）；
  - `author_fingerprint` 与 `authors/` 记录及公钥实际指纹相符；
  - 插件文件存在；
  - 签名文件可通过信任根验签（已签名条目）。
- 拆库演练：复制 `registry/` 至临时目录后可独立校验。

## 作者身份（用户名与指纹）

- `username` 是本地唯一标识，文件名 = username。
- `fingerprint`（公钥 SHA-256 前 16 字节 hex）是生态中**绝对唯一标识**。
- 显示名冲突：同名用户的后缀（`-01`、`-02`…）由 CI 校验连续性，先注册者保持原名。

## 安全要求

- 私钥绝不入库：`.gitignore` 已按 glob 拦截 `*.pem`（仅 `keys/plugin_trust.pub.pem`
  公钥例外放行）、`.env`、`*.key` 等。
- 提交前请运行 `python tools/scan_plugin.py scan plugins/<plugin_id>/` 做发布前安全扫描。
- 插件只应声明运行所需的最小权限（`permissions` 字段）。

## 行为准则

所有贡献者须遵守 `CODE_OF_CONDUCT.md`（Contributor Covenant 2.1）。
