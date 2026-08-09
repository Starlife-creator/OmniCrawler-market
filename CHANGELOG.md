# 生态变更日志（Changelog）

本文件记录 OmniCrawler 插件生态目录（registry）的结构性变更，遵循
Keep a Changelog 格式。插件自身的版本变更记录在各插件目录的 listing.md 中。

## [0.5.0] - 2026-08-09

### 新增

- **模板市场**：`templates/` 目录支持市场模板（声明式配置，与插件共享签名/信任
  机制）；`catalog.json` 新增 `templates` 数组；模板 ID 允许层级命名。
- **git-as-registry 目录结构**：`plugins/*/plugin.yaml` 成为唯一元数据源，
  `catalog.json` 为生成器派生物（禁止手改）。
- **作者身份目录** `authors/<username>.yaml`：公钥指纹（SHA-256 前 16 字节 hex）
  为生态绝对唯一标识；同名显示名带 `-01` 后缀。
- **信任根公钥副本** `keys/plugin_trust.pub.pem`：目录完全自包含。
- **自包含校验工具** `tools/generate_catalog.py`：生成 + `--check`（一致性、
  必填字段、作者指纹、ed25519 验签），仅依赖 PyYAML + cryptography。
- **治理文件**：LICENSE（CC0）、CONTRIBUTING、CODE_OF_CONDUCT、SECURITY、
  CHANGELOG、.gitignore、.env.example、.github/（PR/Issue 模板、CODEOWNERS、
  独立仓库 CI）。
- **发布前安全扫描**（主仓库 `tools/scan_plugin.py`）：敏感扩展名黑名单、
  高熵字符串、API Token 模式、私钥字段、允许列表。

### 变更

- `registry/` 完全自包含：拆库 = 复制目录 + 改应用 `plugins.catalog_url`。
- `catalog.json` 顶层 `trust_public_key_ref` → `keys/plugin_trust.pub.pem`。
