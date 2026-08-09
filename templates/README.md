# 市场模板目录（templates/）

模板是**声明式采集配置**（YAML），与插件（可执行代码）共享同一套签名、信任与
分发机制（Helios 三层体系：插件 / 模板 / 分块模板）。

```
templates/<market_id>/
├── template.yaml          # 模板源（现有模板格式；template: 块含市场字段）
├── template.yaml.sig      # 签名（维护者签名；创作者签名时另有 creator.sig）
├── creator.identity       # 创作者身份（可选，P2P 分发形态）
├── creator.sig            # 创作者签名（可选）
├── maintainer.sig         # 维护者签名（市场分发必带）
└── listing.md             # 功能说明（推荐）
```

## template: 块的市场字段

市场模板的 `template:` 元数据块必须声明（内置模板不需要）：

```yaml
template:
  id: <market_id>           # 如 demo/template，允许层级命名
  name: ...
  version: ...
  category: ...
  description: ...
  publisher: <username>     # 必须与 authors/ 记录一致
  author_fingerprint: <fp>  # 创作者公钥指纹（32 位 hex）
  min_core_version: '2.7.0' # 生成 compatible_core = >=2.7.0
```

## 签名与发布

与插件完全一致：

```bash
# 创作者签名（创建即签名，P2P 可用）
python tools/sign_plugin.py creator-sign templates/<id>/ --file template.yaml --username <你>
# 维护者签名（市场分发必带，冷机器执行）
python tools/sign_plugin.py maintainer-sign templates/<id>/ --file template.yaml --private-key <冷存储私钥>
```

生成目录索引：

```bash
python tools/generate_catalog.py   # 扫描 plugins/ + templates/
```

CI 门禁自动覆盖：模板必填字段、作者指纹匹配、签名验签、catalog.json 一致性。

## 应用端消费

- CLI：`python tools/market.py templates list|info|install|verify`
- GUI：市场面板 →「模板」页
- 安装到 `templates_installed/<id>/`，模板库（`TemplateCatalog` 用户目录）自动发现。
