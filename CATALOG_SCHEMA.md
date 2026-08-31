# Catalog Schema（`catalog.json`）

`catalog.json` 是插件市场的**索引文件（派生物）**。应用端的「市场面板」读取它，向用户展示
可安装插件，并据此下载、验签、安装。

> ⚠️ **不要手改 `catalog.json`**。它是 `tools/generate_catalog.py` 从
> `plugins/<id>/plugin.yaml`（每个插件一个，唯一元数据源）与
> `templates/<id>/template.yaml`（每个模板一个）聚合生成的。修改元数据
> 请编辑对应的 YAML 后运行 `python tools/generate_catalog.py`。
> CI（`.github/workflows/validate.yml`）会用 `--check` 校验生成物一致性。

## 顶层字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_version` | int | catalog 格式版本，当前 `1` |
| `generated_at` | string (ISO8601) | 生成时间，便于缓存失效（一致性校验时忽略） |
| `publisher` | string | 目录发布者（默认取首个插件的发布者，可用 `--publisher` 覆盖） |
| `trust_model` | string | 信任模型，当前为 `dual-rail-ed25519`：创作者和维护者分别签署同一份整包 manifest |
| `trust_public_key_ref` | string | 验签公钥引用（相对 registry 基址的路径，本目录 `keys/plugin_trust.pub.pem`；与应用 `plugins.trust_public_key` 是同一把公钥） |
| `plugins` | array | 已审核插件条目数组 |
| `templates` | array | 已审核模板条目数组（可为空） |
| `sequence` | int | 单调递增目录版本号（每次生成更新）。客户端防重放：拒绝接受 sequence 回退的 catalog |
| `tombstones` | array | **可选**（仓库根存在 `tombstones.json` 时输出）。已下架条目 `[{id, removed_at, reason}]`；与现存插件/模板目录冲突会被生成器拒绝（下架条目不得在线）。应用端据此给出"已下架"提示而非静默缺失 |

## 插件条目字段（`plugins[]`）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✓ | 插件唯一 ID，正则 `^[a-z][a-z0-9_-]{1,63}$` |
| `name` | string | ✓ | 展示名 |
| `version` | string (semver) | ✓ | 插件版本 |
| `publisher` | string | ✓ | 发布者 |
| `category` | string | ✓ | 市场业务分类，仅用于展示与检索，可以由开发者命名。它不决定运行路由 |
| `plugin_types` | array[string] | 新条目必填 | 宿主控制的运行扩展点。支持 `source/fetcher/processor/exporter/auth_provider/parser/extractor/transformer/hook/resource_provider/view`；`view` 是宿主固定组件的隔离声明式界面，原生 `ui` 仅限受信任本地契约 1 插件，不进入市场。旧条目缺失时客户端可从 category/tags 保守推断 |
| `summary` | string | ✓ | 一句话功能摘要 |
| `description_file` | string | ✓ | **功能说明**文件相对路径（即 `listing.md`） |
| `plugin_file` | string | ✓ | 插件代码相对路径 |
| `signature_file` | string | ✓ | detached 签名相对路径（与 `plugin_file` 同名 + `.sig`） |
| `signature_algorithm` | string | ✓ | 当前固定 `ed25519` |
| `permissions` | array[string] | ✓ | 插件声明的权限列表（空数组表示无） |
| `compatible_core` | string | ✓ | 兼容的核心版本约束，如 `>=2.7.0` |
| `license` | string | ✓ | 无隐式默认。插件须为 SPDX 白名单内标识：`AGPL-3.0-only/or-later`、`GPL-3.0-only/or-later`、`MIT`、`Apache-2.0`、`BSD-2-Clause/3-Clause`、`CC0-1.0`、`Unlicense`；白名单外（如 `GPL-2.0-*`、`CC-BY-NC-*`、`LicenseRef-*`）拒绝。模板的 license 为数据与服务条款说明，使用自由文本但仍必填 |
| `execution_mode` | string | | `in_process` \| `subprocess`；缺省为 `subprocess`，非法枚举拒绝。`in_process` 需要显式高风险审批 |
| `domains` | array[string] | | network 权限的域名白名单（随 domains 同机制受门 1 校验） |
| `input_files` | array[string] | | `files:read` 权限的路径白名单；不得使用旧字段名 `files` |
| `required_capabilities` | object | | 契约 2 宿主能力最低协议版本，例如 `{"records.page": ">=1"}`；不满足时客户端在执行插件代码前拒载 |
| `state_schema_version` | integer | | 插件私有状态 schema，正整数；升级时必须显式迁移，插件版本升级本身不切断状态 |
| `release_channel` | string | | `stable` \| `beta`；beta 强制 subprocess + 界面标注"测试版" |
| `dependencies` | array[object] | | `[{name, version, license}]`；空数组合法。门 3 校验声明↔实测导入图双向一致 + 许可白名单 |
| `review_depth` | string | | `reviewed` \| `signed_only`——质量信号（非安全门禁），GUI 展示，T3 申请时参考 |
| `gates_evidence` | object | | 门禁证据摘要，包括检查状态、时间戳和 tag 哈希；随 catalog 签名覆盖，供离线审批验证 |
| `creator_signature_file` / `creator_identity_file` | string | | 旧版单文件创作者签名与公钥身份字段；现代包使用下方整包签名字段 |
| `package_manifest_file` | string | 现代包必填 | 创作者签名的规范整包 manifest 路径 |
| `creator_package_signature_file` | string | 现代包必填 | 创作者对整包 manifest 的签名 |
| `maintainer_package_signature_file` | string | 发布态必填 | 维护者对同一 manifest 字节的复签 |
| `package_manifest_sha256` | string | 现代包必填 | catalog 固定的 manifest SHA-256 |
| `tags` | array[string] | | 标签，便于检索 |
| `updated_at` | string (date) | | 最近更新日期 |
| `homepage` | string (URL) | | 插件主页（可选） |

声明式资源与界面权限中，`resources:read` 只访问用户明确授予的不透明目录句柄；
`surfaces:background` 只控制宿主拥有的背景表面；`render:local` 允许断网本地 HTML 快照；
`render:scripted` 额外允许在隔离 Chromium 中执行本地脚本或最高 5 FPS 的受限帧流，属于高风险
独立授权。市场仍不接受
第三方 QWidget、QSS、绘制回调或任意网页嵌入。

## 模板条目字段（`templates[]`）

模板与插件共享整包双签、作者归属和 catalog 验证机制。条目由生成器从
`templates/<id>/template.yaml` 的 `template:` 块提取：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 模板 ID，允许层级命名（`generic/single-page`） |
| `name` / `version` / `category` | | 取自 `template:` 块 |
| `publisher` / `author_fingerprint` | | 市场字段（`template:` 块必填，须与 `authors/` 一致） |
| `summary` | string | 取自 `template:` 块的 `description` |
| `template_file` | string | 模板文件相对路径（`templates/<id>/template.yaml`） |
| `signature_file` | string | 签名相对路径（`templates/<id>/template.yaml.sig`） |
| `description_file` | string | 功能说明相对路径（存在 `listing.md` 时生成） |
| `compatible_core` | string | `>=` + `template:` 块的 `min_core_version` |
| `license` / `tags` / `updated_at` | | 取自 `template:` 块（`updated_at` ← `verified_at`） |
| `package_manifest_file` / `creator_package_signature_file` / `maintainer_package_signature_file` / `package_manifest_sha256` | string | 与插件相同的现代整包双签字段；模板不再使用较弱的旁路信任模型 |

## 清单源（`plugins/<id>/plugin.yaml`）

每个插件一个 YAML 文件，是 `catalog.json` 条目的唯一数据源。字段与上表完全一致，
另外多两个字段（**不**进入 `catalog.json` 条目）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `author_fingerprint` | string | ✓ | 发布者公钥指纹（SHA-256 前 16 字节 hex），必须与 `authors/` 中该发布者的记录一致 |
| `permissions` | array[string] | ✓ | 同 catalog 条目 |

生成器会拒绝清单中的未知字段（防止拼写错误静默丢弃）。

### 作者记录（`authors/<market_handle>.yaml`）

每个发布者一个 YAML 文件（文件名 = `username`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `market_handle` | string | 市场内唯一且稳定的句柄；文件名必须与它一致 |
| `requested_username` | string | 创作者本地请求名，可以与其他指纹重复 |
| `username` | string | 兼容字段，现代记录等于 `market_handle` |
| `display_name` | string | 展示名；不参与身份验证 |
| `pubkey_ref` | string | 签名公钥 PEM 的相对路径（相对于 `authors/` 目录） |
| `fingerprint` | string | 公钥 SHA-256（ed25519 公钥原始 32 字节）前 16 字节 hex |
| `roles` | array[string] | 角色，如 `[publisher]` |

生成器会计算 `pubkey_ref` 指向公钥的实际指纹，与声明的 `fingerprint` 比对，二者必须一致。
同一指纹总是复用已有 handle；请求名冲突时，正式发布工具为后来者分配连续 `-01`、`-02`
后缀。所有归属校验认指纹，不认显示名。

## 投稿态（不进入 catalog）

外部贡献位于
`submissions/<plugins|templates>/<creator_fingerprint>/<package_id>/`，包含创作者签名包和
`submission.json`。该目录只接受静态检查，不是可见市场条目。维护者运行
`finalize_submission.py` 后才生成 `market.yaml`、维护者签名、作者记录和已签名 catalog。

现代正式条目使用市场拥有的 `market.yaml` overlay。overlay 可以更新市场展示与审核状态，
但 `package.manifest.json` 及其声明的作者载荷必须保持原字节。后续版本保存于
`versions/<semver>/`，overlay 指向当前版本。

## 路径约定（迁移友好）

- `description_file` / `plugin_file` / `signature_file` 全部是**相对于 catalog 基址**的路径。
- catalog 基址由应用配置 `plugins.catalog_url` 决定（默认主仓库 raw 地址）。
- 因此移动整个生态目录到新仓库/新服务后，只需改 `catalog_url`，条目内路径不变。

## 签名与验签

- 现代条目必须先验证 `catalog.json.sig`，再下载 manifest 声明的全部文件；客户端同时验证
  创作者和维护者对同一份 manifest 的签名、catalog 固定的 manifest SHA-256 以及精确文件集合。
- `signature_file` 等单文件字段只用于兼容已发布的旧版存量条目，不是新投稿的签名模型。
- 任一验签、哈希、文件集合、包 ID 或版本检查失败时，客户端必须 fail-closed 拒绝安装或加载，
  并在市场面板标记该条目不可信。
- 撤销：生态注册表 `EcosystemRegistry.revoke(package_id, version, advisory)` 记录撤回；
  重新生成 catalog 时把被撤回条目移除或标记。
