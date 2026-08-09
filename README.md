# OmniCrawler 插件生态目录（Plugin Registry）

本目录是 OmniCrawler **策展式插件市场**的目录源，采用 **git-as-registry** 模式：
目录结构即索引——每个插件一个 `plugin.yaml` 清单，`authors/` 记录发布者公钥指纹，
`catalog.json` 是**派生物**（由 `tools/generate_catalog.py` 聚合生成，随仓库提交）。

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

## 目录结构

```
OmniCrawler-market/
├── catalog.json                 # 【派生物】索引：由生成器从 plugin.yaml 聚合（勿手改）
├── CATALOG_SCHEMA.md            # catalog.json + plugin.yaml 字段说明
├── README.md                    # 本文件
├── LICENSE                      # CC0 1.0（生态元数据公共领域）
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
│   ├── generate_catalog.py      # 【自包含】生成/校验工具（仅依赖 PyYAML + cryptography）
│   └── scan_plugin.py           # 【自包含】发布前安全扫描（纯标准库）
├── authors/                     # 发布者公钥指纹记录（信任身份目录）
│   └── <username>.yaml          # username / pubkey_ref / fingerprint（SHA-256 前 16 字节 hex）
├── plugins/
│   └── <plugin_id>/             # 每个插件一个目录，id 用小写字母/数字/下划线/短横线
│       ├── plugin.yaml          # 【唯一元数据源】插件清单（机器可读）
│       ├── plugin.py            # 插件代码（必须含 def register(registry)）
│       ├── plugin.py.sig        # 与 plugin.py 同名的 detached ed25519 签名
│       └── listing.md           # 强制功能说明（人类可读）
└── templates/                   # 市场模板（声明式配置，与插件共享签名/信任机制）
    ├── README.md                # 模板市场说明（结构 + 市场字段 + 签名流程）
    └── <market_id>/             # 每个模板一个目录（id 允许层级命名，如 demo/template）
        ├── template.yaml        # 模板源（template: 块含 publisher/author_fingerprint）
        ├── template.yaml.sig    # detached ed25519 签名
        ├── creator.identity     # 创作者身份（可选，P2P 形态）
        ├── creator.sig          # 创作者签名（可选）
        ├── maintainer.sig       # 维护者签名（市场分发必带）
        └── listing.md           # 功能说明（推荐）
```

## 信任模型

- **单信任根 ed25519**：签名用持有者冷存储的私钥生成，验签用随包分发的公钥
  `configs/plugin_trust.pub.pem`（本目录 `keys/` 存有一份相同副本，拆库后独立可用）。
- 应用加载插件前会 fail-closed 验签；验签失败直接拒载。
- 贡献者无法自签——提交后由持有私钥的发布者审核并签名，签名即背书。
- `authors/<username>.yaml` 的 `fingerprint`（公钥 SHA-256 前 16 字节 hex）是
  生态中**绝对唯一标识**；插件清单必须声明 `author_fingerprint` 且与作者记录一致。

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

1. 在 `plugins/` 下新建 `<plugin_id>/` 目录。
2. 放入 `plugin.py`（含 `def register(registry)`）与 **强制的** `listing.md`
   （说明：做什么、适用场景、权限、兼容、作者、版本、许可）。
3. 新建 `plugin.yaml` 清单（字段见 `CATALOG_SCHEMA.md`），`publisher` 与
   `author_fingerprint` 必须能在 `authors/` 中找到对应记录（首次发布先提交
   `authors/<username>.yaml`）。
4. 通过插件契约测试（主仓库 `tests/unit/plugin/`）。
5. 提交 PR；维护者审核 `listing.md` 与代码。
6. 审核通过后，由持有冷私钥的发布者在**冷机器**上签名：
   `python tools/sign_plugin.py sign plugins/<plugin_id>/plugin.py`
    （私钥位于维护者冷存储介质，绝不入库）。
7. 运行 `python tools/generate_catalog.py` 重新生成 `catalog.json`，一并合并。

> CI 门禁（`.github/workflows/validate.yml`）：PR 若修改 `plugins/`、`authors/`、
> `keys/` 或 `catalog.json`，自动执行 `tools/generate_catalog.py --check`——校验
> plugin.yaml 合法、与 `catalog.json` 一致、`author_fingerprint` 有作者记录且与
> 公钥实际指纹相符、`plugin.py.sig` 能通过信任根验签，否则阻断合并。

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
