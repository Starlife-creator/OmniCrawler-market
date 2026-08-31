# OmniCrawler 插件与模板市场

本仓库是 OmniCrawler 的静态、可镜像市场目录，采用 git-as-registry 模式。它不依赖账号
服务器或市场 API：作者身份由 Ed25519 公钥指纹确认，`catalog.json` 是从正式包生成并由
维护者签名的索引。

插件和模板在投稿前就是作者拥有的可分享文件夹。作者可以只进行私下分享，也可以把同一份
创作者签名包投稿市场。私下分享不等于市场审核，投稿状态也不能作为市场包安装。

## 仓库与主项目布局

源码开发时，主仓库与市场仓库应位于同一父目录：

```text
workspace/
├── OmniCrawler/
└── OmniCrawler-market/
```

市场目录内部只使用相对路径，因此可以整体复制到其他 Git 仓库或静态文件服务。镜像只复制
catalog、包和签名，不重签，也不会改变原有信任等级。

## 许可证

| 范围 | 许可 |
|---|---|
| 仓库根元数据、目录和文档 | CC0-1.0，见 `LICENSE` |
| `tools/` 工具代码 | MIT，见 `tools/LICENSE` |
| 各插件代码 | 以包内 SPDX 许可声明为准 |
| 各模板及其数据来源 | 以模板声明和第三方服务条款为准 |

市场允许的插件许可证及字段规则见 [CATALOG_SCHEMA.md](CATALOG_SCHEMA.md)。仓库许可不会
覆盖或替代插件依赖、模板数据源及第三方内容原有的许可义务。

## 信任模型

现代包采用整包双签：

1. `package.manifest.json` 固定包类型、ID、版本、创作者指纹、完整文件集合和 SHA-256；
2. 创作者用 `package.manifest.creator.sig` 签署 manifest 原始字节；
3. 审核通过后，维护者用 `package.manifest.maintainer.sig` 复签同一份原始字节；
4. 客户端先验证 `catalog.json.sig`，再验证两份包签名、manifest 哈希和精确文件集合。

市场不得修改创作者签名覆盖的内容。展示名、稳定 `market_handle`、审核状态和其他市场字段
放在独立 `market.yaml` 中。

创作者签名只证明包来自某把创作者密钥；维护者复签只证明市场审核过这些固定字节。两者都
不能证明第三方服务永远安全、合法或可用。

## 身份与重名

- 包归属只认创作者公钥指纹，不认用户名；
- 本地用户名允许重复；
- 首次正式发布时才分配唯一、稳定的 `market_handle`；
- 请求名冲突时，后来者依次获得 `-01`、`-02` 后缀；
- 同一指纹发布新包或更新时继续使用原 handle；
- 已发布的包 ID 不能转移给另一把密钥。

## 目录结构

```text
OmniCrawler-market/
├── catalog.json
├── catalog.json.sig
├── tombstones.json                 # 可选的撤销记录源
├── submissions/
│   ├── plugins/<fingerprint>/<id>/
│   └── templates/<fingerprint>/<id>/
├── plugins/<market-directory>/
├── templates/<market-directory>/
├── authors/<market_handle>.yaml
├── keys/plugin_trust.pub.pem
├── tools/
├── CATALOG_SCHEMA.md
├── CONTRIBUTING.md
└── SECURITY.md
```

`submissions/` 是外部贡献者唯一可以写入的生态内容入口。正式 `plugins/`、`templates/`、
`authors/`、`catalog.json`、`catalog.json.sig` 和维护者签名均由审核发布流程生成。

## 创作者签名包

插件包通常包含：

```text
plugin-folder/
├── plugin.py
├── plugin.yaml
├── listing.md
├── creator.identity
├── package.manifest.json
└── package.manifest.creator.sig
```

模板包使用 `template.yaml` 代替 `plugin.py` 和 `plugin.yaml`。manifest 可以覆盖其他必要文件，
但实际文件集合必须与 manifest 完全一致，不能多文件、少文件或哈希漂移。

## 投稿流程

1. 在 OmniCrawler 中完成插件或模板并运行本地验证；
2. 使用创作者本地身份完成整包签名；
3. 按需先私下分享和测试；
4. 选择投稿市场，检查公开文件、权限、域名、依赖和数据来源；
5. 明确接受 DCO，创建带 `Signed-off-by` 的 Draft PR；
6. PR 只能修改对应的 `submissions/` 路径；
7. CI 进行签名、哈希、路径、AST/YAML、依赖、许可、凭据泄漏和 DCO 静态检查；
8. 维护者人工审核固定 manifest 哈希，必要时在一次性隔离环境动态测试；
9. 维护者复签同一份 manifest，生成正式目录、市场 overlay、作者记录和已签名 catalog。

详细要求见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全模型和漏洞报告渠道见
[SECURITY.md](SECURITY.md)。

## 插件要求

- 新插件必须使用契约 2：`handle(operation, payload) -> dict`；
- 契约 2 市场插件可接入全部正式数据扩展点，以及 `resource_provider` 和宿主渲染的声明式 `view`；
- `plugin_types` 是受控运行扩展点；自由业务分类使用 `category`，检索词使用 `tags`；
- `PLUGIN_METADATA` 必须是可静态读取的 `dict` 字面量；
- 默认 `execution_mode: subprocess`；
- 权限、域名、输入文件和依赖必须完整、准确且最小化；
- 网络和文件访问必须分别提供精确白名单；
- 声明式视图只能使用宿主白名单组件；目录使用用户授权句柄，媒体表面和本地 HTML 快照由宿主控制；
- 插件许可必须使用市场允许的 SPDX 标识；
- `listing.md` 必须说明功能、数据流向、权限理由、兼容性、许可和限制。

## 模板要求

- 使用安全可解析的声明式 YAML；
- `template.id` 和 `template.version` 与 manifest 一致；
- `domains` 只包含小写主机名，固定 seed 主机必须被覆盖；
- 凭据只使用 `secret://name` 引用，禁止提交真实密钥；
- `listing.md` 说明数据来源、服务条款、频率限制、礼貌延迟、API Key 和数据许可。

## Catalog 与更新

`catalog.json` 是派生物，禁止手工编辑。正式发布工具从包元数据、作者记录和市场 overlay
生成 catalog，并签署其原始字节。字段定义见 [CATALOG_SCHEMA.md](CATALOG_SCHEMA.md)。

更新要求：

- 使用原包归属的同一创作者密钥；
- SemVer 严格递增；
- 新版本保存到 `versions/<version>/`，不覆盖旧版创作者签名字节；
- 审核和复签成功后，市场 overlay 才指向新版本；
- 同版本覆盖、降级和换密钥接管均被拒绝。

## 自建镜像与离线使用

把整个目录复制到目标仓库或静态服务，并将应用的 `plugins.catalog_url` 指向新基址即可。
离线发行版可以使用内置快照。客户端仍须验证原始 catalog 和包签名，并拒绝 catalog sequence
或可信时间回退。镜像方不得用自己的签名替换原签名来冒充原市场。
