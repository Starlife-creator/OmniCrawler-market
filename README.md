# OmniCrawler 插件生态目录（Plugin Registry）

本目录是 OmniCrawler **策展式插件市场**的目录源，采用 **git-as-registry** 模式：
目录结构即索引——每个插件一个 `plugin.yaml` 清单，`authors/` 记录发布者公钥指纹，
`catalog.json` 是**派生物**（由 `tools/generate_catalog.py` 聚合生成，随仓库提交）。

> 当前贡献协议：作者完成插件或模板后先生成可私下分享的整包签名目录，再自主选择是否把
> 同一份字节投稿到 `submissions/`。外部贡献者不直接写正式目录。维护者审核后复签同一个
> `package.manifest.json`，生成 `market.yaml`、稳定 `market_handle` 和带签名的 catalog。
> 详细流程以 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [SECURITY.md](SECURITY.md) 为准；
> 下文中的 `plugin.yaml`/单文件签名描述也覆盖仍受支持的旧版存量条目。

> 设计原则：**所有文件路径都是相对于本目录（catalog 基址）的相对路径**。本目录
> **完全自包含**（公钥、校验工具都在目录内，不引用主仓库任何文件）。因此把本目录
> 复制到任何位置、任何仓库、任何静态 HTTP 服务后，只要把应用配置里的
> `plugins.catalog_url` 改成新基址，目录内部无需任何改动。

---

## 仓库布局（与主仓库同级）

插件市场与主仓库是**两个独立仓库**，源码开发时需放在同一父目录下、目录名保持默认：

```
你的任意目录/
├── OmniCrawler/            # 主仓库（应用 + 引擎 + 插件生态）
└── OmniCrawler-market/     # 本仓库（插件市场）
```

```powershell
git clone https://github.com/<owner>/OmniCrawler
git clone https://github.com/<owner>/OmniCrawler-market
```

布局依赖（目录名与同级关系不可变，路径前缀无关）：

| 组件 | 引用方式 |
|---|---|
| 主仓库 `tools/market.py`、`tools/sign_plugin.py` | `../OmniCrawler-market` |
| 主仓库 GUI 插件/模板市场 | 无 `catalog_url` 时回退到 `../OmniCrawler-market` 本地浏览 |
| 主仓库 `tests/unit/plugin/` | 市场相关测试引用同级市场仓库；未 clone 时自动跳过 |

只 clone 主仓库时应用完全可用（无市场目录即视为未配置市场）；使用插件市场需同时
clone 两个仓库到同一父目录。

## 许可证（双层结构）

| 范围 | 许可 | 说明 |
|---|---|---|
| 仓库根元数据与内容 | **CC0 1.0**（`LICENSE`） | plugin.yaml 清单、authors/ 作者记录、catalog.json、文档、公钥、CI 配置——公共领域，自由复制/修改/分发/镜像 |
| `tools/` 工具代码 | **MIT**（`tools/LICENSE`） | generate_catalog.py、scan_plugin.py，文件头含 SPDX 声明 |
| `plugins/*/` 插件代码 | 各插件自声明 | 以各插件 `plugin.yaml` 的 `license` 字段为准（如 example_news 为 MIT） |

选择依据：元数据是**生态公共资产**（镜像、离线、审查零摩擦），故 CC0；工具代码
保留署名与免责声明，故 MIT；插件代码归各作者自行决定。

## 目录结构

```
OmniCrawler-market/
├── catalog.json                 # 【派生物】索引：由生成器从 plugin.yaml 聚合（勿手改）
├── catalog.json.sig             # 目录原始字节的维护者签名；客户端解析前验证
├── submissions/                 # 创作者签名投稿态；外部 PR 唯一内容入口
├── CATALOG_SCHEMA.md            # catalog.json + plugin.yaml 字段说明
├── README.md                    # 本文件
├── LICENSE                      # CC0 1.0（生态元数据公共领域；tools/ 例外见下）
├── CONTRIBUTING.md              # 贡献指南（插件提交流程 + DCO）
├── CODE_OF_CONDUCT.md           # Contributor Covenant 2.1
├── SECURITY.md                  # 信任模型、私钥红线、漏洞报告
├── CHANGELOG.md                 # 生态变更日志
├── .gitignore                   # 私钥/凭据 glob 拦截（公钥例外放行）
├── .env.example                 # 环境变量占位模板
├── .github/                     # PR/Issue 模板、CODEOWNERS、独立仓库 CI（validate.yml）
├── keys/
│   └── plugin_trust.pub.pem     # 信任根公钥副本（与主仓库 configs/ 同内容，公钥公开）
├── tools/
│   ├── LICENSE                  # MIT（本目录工具代码的单独许可）
│   ├── generate_catalog.py      # 【自包含】生成/校验工具（仅依赖 PyYAML + cryptography）
│   └── scan_plugin.py           # 【自包含】发布前安全扫描（纯标准库）
├── authors/                     # 发布者公钥指纹记录（信任身份目录）
│   └── <username>.yaml          # username / pubkey_ref / fingerprint（SHA-256 前 16 字节 hex）
├── plugins/
│   └── <plugin_id>/             # 每个插件一个目录，id 用小写字母/数字/下划线/短横线
│       ├── market.yaml          # 【现代条目】市场 overlay，不改写创作者包
│       ├── package.manifest.json
│       ├── package.manifest.creator.sig
│       ├── package.manifest.maintainer.sig
│       ├── plugin.yaml          # 【唯一元数据源】插件清单（机器可读）
│       ├── plugin.py            # 插件代码（必须含 def register(registry)）
│       ├── plugin.py.sig        # 与 plugin.py 同名的 detached ed25519 签名
│       └── listing.md           # 强制功能说明（人类可读）
└── templates/                   # 市场模板（声明式配置，与插件共享签名/信任机制）
    ├── README.md                # 模板市场说明（结构 + 市场字段 + 签名流程）
    └── <market_id>/             # 每个模板一个目录（id 允许层级命名，如 demo/template）
        ├── template.yaml        # 模板源（template: 块含 publisher/author_fingerprint）
        ├── template.yaml.sig    # 最终分发签名（维护者用冷密钥 `sign` 覆盖此文件；下载端/CI 校验它）
        ├── creator.identity     # 创作者身份（可选，P2P 形态）
        ├── creator.sig          # 创作者签名（可选）
        └── listing.md           # 功能说明（推荐）
```

## 信任模型

双轨签名（2026-08 起），两条轨签署同一整包 manifest，独立验签、互不替代：

- **维护者轨（分发签名，单信任根 ed25519）**：现代包使用
  `package.manifest.maintainer.sig`，旧包继续兼容 `plugin.py.sig` / `template.yaml.sig`；
  签名用维护者冷存储私钥生成，验签公钥随包分发
  （`configs/plugin_trust.pub.pem`，本目录 `keys/` 存有相同副本，拆库后独立可用）。
  应用加载前 fail-closed 验签；验签失败直接拒载。**模板强制此轨**；
  插件可选（仅有创作者轨亦可通过生成器完整性校验）。
- **创作者轨**：贡献者用本地身份签署整包 manifest
  （`creator.identity` + `package.manifest.creator.sig`，`creator.sig` 为旧客户端兼容轨），
  公钥指纹记录在 identity 中）。创作者签名可过生成器完整性校验，但**不构成
  市场背书**：非市场来源（本地安装）按 CreatorTrusted/CreatorUntrusted 分级
  （不在信任列表则拒绝或弹窗询问）；**市场来源**插件则只认维护者签名，
  创作者签名在加载端一律拒绝。即："无法自签"仅对模板成立，且创作者轨
  不能替代分发签名被最终用户加载。
- `authors/<market_handle>.yaml` 的 `fingerprint`（公钥 SHA-256 前 16 字节 hex）是
  生态中**绝对唯一标识**；插件清单必须声明 `author_fingerprint` 且与作者记录一致。
- 正式发布会把 `creator.identity` 派生指纹与作者记录、包归属和 market overlay 交叉校验；
  用户名重复时在市场发布态分配稳定后缀，身份判断始终认指纹不认名字。

## catalog.json 是派生物

`catalog.json` 由生成器从 `plugins/*/plugin.yaml` 与 `templates/*/template.yaml`
聚合生成，**不要手改**。应用端（`market_client` / GUI 市场面板 / `tools/market.py`）
只读它。

```bash
# 修改了插件/模板清单后重新生成
python tools/generate_catalog.py

# 只校验不写盘（CI 门禁：一致性 + 必填字段 + 作者指纹 + 签名验签）
python tools/generate_catalog.py --check
```

## 发布前安全扫描

提交插件前运行发布前安全扫描（五步：敏感文件黑名单、高熵字符串、API Token 模式、
私钥字段、允许列表）：

```bash
python tools/scan_plugin.py scan plugins/<plugin_id>/
# 可选：--manifest plugins/<plugin_id>/plugin.yaml 启用允许列表校验（声明 files 字段）
```

签名工具（主仓库 `tools/sign_plugin.py sign`）会在签名前自动执行本扫描，发现问题
中止签名（`--skip-scan` 可跳过，不推荐）。

## 提交一个新插件（贡献流程）

> 以下直接编辑正式目录的步骤仅适用于维护旧版存量条目。新插件和新模板必须按
> [CONTRIBUTING.md](CONTRIBUTING.md) 进入 `submissions/`，再由维护者运行
> `finalize_submission.py` 生成正式目录；贡献者不生成维护者签名或 catalog。

1. 在 `plugins/` 下新建 `<plugin_id>/` 目录。
2. 放入 `plugin.py`（含 `def register(registry)`）与 **强制的** `listing.md`
   （说明：做什么、适用场景、权限、兼容、作者、版本、许可）。
3. 新建 `plugin.yaml` 清单（字段见 `CATALOG_SCHEMA.md`），`publisher` 与
   `author_fingerprint` 必须能在 `authors/` 中找到对应记录（首次发布先提交
   `authors/<username>.yaml`）。
4. 通过插件契约测试（主仓库 `tests/unit/plugin/`）。
5. 提交 PR；维护者审核 `listing.md` 与代码。
6. 分发签名：
   - **模板（必经此步）**：审核通过后，由持有冷私钥的发布者在**冷机器**上签名
     （覆盖 `template.yaml.sig`，下载端/CI 校验的唯一分发签名）：
     `python tools/sign_plugin.py sign templates/<template_id>/template.yaml`
   - **插件（二选一）**：作者已附创作者轨（`creator.sig` + `creator.identity`）
     即可通过生成器校验；若需要维护者分发背书，由发布者冷签：
     `python tools/sign_plugin.py sign plugins/<plugin_id>/plugin.py`
     （私钥位于维护者冷存储介质，绝不入库。）
     ⚠️ 注意：仅创作者轨的插件虽能进入目录，但应用端对**市场来源**插件
     只认维护者签名——未冷签的市场插件在用户端会被拒绝加载
     （`plugins.py` is_market 分支）。因此对外分发的插件实际上仍需第 6 步冷签；
     创作者轨的意义是让贡献者先入库待审，而非替代分发签名。
7. 运行 `python tools/generate_catalog.py` 重新生成 `catalog.json`，一并合并。

> CI 门禁（`.github/workflows/validate.yml`）：PR 若修改 `plugins/`、`authors/`、
> `keys/` 或 `catalog.json`，自动执行 `tools/generate_catalog.py --check`——校验
> plugin.yaml / template.yaml 合法、与 `catalog.json` 一致、`author_fingerprint` 有作者记录且与
> 公钥实际指纹相符、`plugin.py.sig` / `template.yaml.sig` 能通过信任根验签，否则阻断合并。

## 自建镜像 / 离线使用

本目录**自包含**（公钥 `keys/`、校验工具 `tools/` 都在目录内），克隆即可离线浏览
插件列表与元数据；把应用配置的 `plugins.catalog_url` 指向本仓库即可完成市场切换：

```yaml
plugins:
  catalog_url: "https://raw.githubusercontent.com/<owner>/OmniCrawler-market/main"
```

（离线/便携构建则把本目录打包进应用，并将 `catalog_url` 改为内置快照目录
`bundled_catalog_dir`。镜像方只复制文件、不重签名，原始签名与信任等级不变。）

> 唯一需要双维护的是 `plugin_trust.pub.pem` 的副本同步
> （主仓库 `configs/` ↔ 生态仓库 `keys/`，各存一份）。公钥是公开文件，轮换时两边各更新一次。

> 之所以"简单"，是因为：① 目录自包含、路径全相对（不引用主仓库任何文件）；
> ② 应用只认一个 `catalog_url` 配置；③ 签名信任根跨仓库复用。
> 三者共同保证迁移是"拷贝 + 改一个值"。
