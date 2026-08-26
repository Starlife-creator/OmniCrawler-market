# 生态变更日志（Changelog）

本文件记录 OmniCrawler 插件生态目录（registry）的结构性变更，遵循
Keep a Changelog 格式。插件自身的版本变更记录在各插件目录的 listing.md 中。

## [0.6.0] - 2026-08-26

### 新增

- **双轨签名（B02-020）**：创作者轨 `creator.sig` + `creator.identity` 与维护者
  分发轨并行；模板强制维护者轨，插件二选一可过生成器校验（市场来源插件
  加载仍只认维护者签名，README/CONTRIBUTING 已同步口径）。
- **tombstones.json**：下架墓碑（id/removed_at/reason），与现存目录冲突即拒绝；
  catalog 输出 `tombstones` 数组，应用端给出"已下架"提示。
- **catalog `sequence` 防重放**：单调递增版本号，客户端拒绝回退。
- **门 4 版本规则 + git 基线比对**；`scan_plugin` 显式 `--manifest` 启用
  允许列表校验（B02-018 修复此前空转）。
- `tools/catalog_lib/`：generate_catalog 936 行单文件按域拆分
  （common/schema/authors/tombstones/signing/build/rules/cli）。

### 变更

- `SECURITY.md`：密钥轮换/Shamir 分片从现状时态改为规划（实态=全量重签 +
  口令加密双备份）；`README.md` 信任模型改为双轨实态并标注 U-7 边界；
  `CATALOG_SCHEMA.md` 补 `sequence`/`tombstones` 字段。
- `signing_transparency.jsonl` 降级为 informational-only（无防篡改链），
  历史条目绝对路径已脱敏。

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
