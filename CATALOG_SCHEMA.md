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
| `trust_model` | string | 信任模型，当前 `dual-rail-ed25519`（维护者冷签名 + 创作者热签名双轨，第 64/70 轮修正：原 `single-root-ed25519` 为过时描述） |
| `trust_public_key_ref` | string | 验签公钥引用（相对 registry 基址的路径，本目录 `keys/plugin_trust.pub.pem`；与应用 `plugins.trust_public_key` 是同一把公钥） |
| `plugins` | array | 已审核插件条目数组 |
| `templates` | array | 已审核模板条目数组（可为空） |

## 插件条目字段（`plugins[]`）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✓ | 插件唯一 ID，正则 `^[a-z][a-z0-9_-]{1,63}$` |
| `name` | string | ✓ | 展示名 |
| `version` | string (semver) | ✓ | 插件版本 |
| `publisher` | string | ✓ | 发布者 |
| `category` | string | ✓ | 扩展点类别：`source` / `fetcher` / `processor` / `exporter` / `auth_provider` / `parser` / `extractor` / `transformer` / `hook` |
| `summary` | string | ✓ | 一句话功能摘要 |
| `description_file` | string | ✓ | **功能说明**文件相对路径（即 `listing.md`） |
| `plugin_file` | string | ✓ | 插件代码相对路径 |
| `signature_file` | string | ✓ | detached 签名相对路径（与 `plugin_file` 同名 + `.sig`） |
| `signature_algorithm` | string | ✓ | 当前固定 `ed25519` |
| `permissions` | array[string] | ✓ | 插件声明的权限列表（空数组表示无） |
| `compatible_core` | string | ✓ | 兼容的核心版本约束，如 `>=2.7.0` |
| `license` | string | ✓ | **必填**（Phase 1 起无隐式默认）。插件须为 SPDX 白名单内标识（见门 2）：`AGPL-3.0-only/or-later`、`GPL-3.0-only/or-later`、`MIT`、`Apache-2.0`、`BSD-2-Clause/3-Clause`、`CC0-1.0`、`Unlicense`；白名单外（如 `GPL-2.0-*`/`CC-BY-NC-*`/`LicenseRef-*`）→ 拒绝。模板不适用白名单（license 为数据/服务条款自由文本，但必填） |
| `execution_mode` | string | | `in_process` \| `subprocess`（Phase 1 B1）。**缺省 `subprocess`**（未声明即 subprocess，无兼容语义）；非法枚举拒绝 |
| `domains` | array[string] | | network 权限的域名白名单（随 domains 同机制受门 1 校验） |
| `input_files` | array[string] | | files:read 权限的路径白名单（第 82 轮更名：原 `files` 与 scan_plugin 扫描允许列表冲突） |
| `release_channel` | string | | `stable` \| `beta`；beta 强制 subprocess + 界面标注"测试版" |
| `dependencies` | array[object] | | `[{name, version, license}]`；空数组合法。门 3 校验声明↔实测导入图双向一致 + 许可白名单 |
| `review_depth` | string | | `reviewed` \| `signed_only`——质量信号（非安全门禁），GUI 展示，T3 申请时参考 |
| `gates_evidence` | object | | tag 门禁证据摘要（四门通过状态 + 时间戳 + tag 哈希，随 catalog 签名覆盖；批准矩阵离线凭据，第 78 轮） |
| `creator_signature_file` / `creator_identity_file` | string | | 创作者轨签名与公钥身份（与维护者轨独立验签，B02-020 双轨） |
| `tags` | array[string] | | 标签，便于检索 |
| `updated_at` | string (date) | | 最近更新日期 |
| `homepage` | string (URL) | | 插件主页（可选） |

## 模板条目字段（`templates[]`）

模板与插件共享信任/签名机制（Helios 三层体系）。条目由生成器从
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

## 清单源（`plugins/<id>/plugin.yaml`）

每个插件一个 YAML 文件，是 `catalog.json` 条目的唯一数据源。字段与上表完全一致，
另外多两个字段（**不**进入 `catalog.json` 条目）：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `author_fingerprint` | string | ✓ | 发布者公钥指纹（SHA-256 前 16 字节 hex），必须与 `authors/` 中该发布者的记录一致 |
| `permissions` | array[string] | ✓ | 同 catalog 条目 |

生成器会拒绝清单中的未知字段（防止拼写错误静默丢弃）。

### 作者记录（`authors/<username>.yaml`）

每个发布者一个 YAML 文件（文件名 = `username`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `username` | string | 发布者用户名 |
| `display_name` | string | 展示名（可带后缀区分同名用户） |
| `pubkey_ref` | string | 签名公钥 PEM 的相对路径（相对于 `authors/` 目录） |
| `fingerprint` | string | 公钥 SHA-256（ed25519 公钥原始 32 字节）前 16 字节 hex |
| `roles` | array[string] | 角色，如 `[publisher]` |

生成器会计算 `pubkey_ref` 指向公钥的实际指纹，与声明的 `fingerprint` 比对，二者必须一致。

## 路径约定（迁移友好）

- `description_file` / `plugin_file` / `signature_file` 全部是**相对于 catalog 基址**的路径。
- catalog 基址由应用配置 `plugins.catalog_url` 决定（默认主仓库 raw 地址）。
- 因此移动整个生态目录到新仓库/新服务后，只需改 `catalog_url`，条目内路径不变。

## 签名与验签

- 下载 `plugin_file` 与 `signature_file` 后，用信任根公钥验证 `signature_file` 是否覆盖 `plugin_file` 字节。
- 验签失败的应用端行为：fail-closed 拒载，并在市场面板标记该插件「不可信」。
- 撤销：生态注册表 `EcosystemRegistry.revoke(package_id, version, advisory)` 记录撤回；
  重新生成 catalog 时把被撤回条目移除或标记。
