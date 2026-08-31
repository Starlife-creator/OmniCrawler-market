# 贡献插件与模板

市场采用“先形成可私下分享的创作者签名包，再自主选择是否投稿”的流程。贡献者只提交
`submissions/`，不直接修改 `plugins/`、`templates/`、`authors/`、`catalog.json` 或任何
维护者签名。发布目录属于维护者发布态。

## 一份包，两种去向

完成制作后，插件或模板目录已经包含：

- `package.manifest.json`：规范 JSON，记录包类型、ID、版本、创作者指纹和所有载荷哈希；
- `package.manifest.creator.sig`：创作者对整个 manifest 的 ed25519 签名；
- `creator.identity`：公开身份和公钥；
- `plugin.py` 或 `template.yaml`、`listing.md` 及其他被 manifest 覆盖的文件。

此时目录已经可以直接发给其他用户。接收方会看到来源、指纹、权限和域名，确认后安装；
私下分享不等于市场审核。也可以用同一目录创建 Draft PR，不需要重新打包。

## 正规投稿流程

1. 在 OmniCrawler 的市场首页创建/选择插件或模板，填写说明并点击“完成并签名”。
2. 本地验证整包签名，先按需私下测试。
3. 选择“投稿市场”，阅读权限、域名、公开内容和 DCO 提示。
4. 明确勾选 DCO 后，由应用创建带 `Signed-off-by` 的 Draft PR。
5. PR 中只能新增或更新：
   `submissions/<plugins|templates>/<creator_fingerprint>/<package_id>/`。
6. CI 只做规范 JSON、签名、哈希、路径、静态 AST/YAML、凭据泄漏和 DCO 检查；
   **不会 import 或执行投稿代码**。
7. 维护者人工审核准确的 manifest 哈希、代码、最小权限、域名、依赖、许可和说明。
8. 维护者用冷私钥复签同一个 manifest，生成市场元数据、稳定市场用户名和已签名目录。
9. `publish-check` 要求每个可见条目都有维护者整包签名，且 `catalog.json.sig` 有效后才可发布。

CLI 的模板投稿必须显式加入 `--accept-dco`；不想创建 PR 时使用 `--no-pr`，生成的仍是
可私下分享的创作者签名包/投稿目录。

## 身份与重名

- 身份归属只认 ed25519 公钥指纹，不认用户名。
- 本地用户名允许在不同设备、不同用户之间重复。
- 首次正式发布时，市场按指纹分配稳定 `market_handle`。若 `alice` 已被其他指纹占用，
  后来者依次得到 `alice-01`、`alice-02`；同一指纹再次发布沿用原 handle。
- 维护者不能改写创作者签名中的包 ID，也不能把现有 ID 转给另一把密钥。冲突时作者需换 ID
  后重新签名。

## 更新已有包

- 使用拥有该包的同一创作者密钥重新签名；
- 版本必须是 SemVer，并严格高于市场当前版本；
- 新版保存到 `versions/<version>/`，不会覆盖旧版创作者签名字节；
- 市场 overlay 和签名目录切换到通过复核的新版本；旧版仍由 Git 历史和版本目录保留；
- 降级、同版本覆盖、换密钥接管均会被发布工具拒绝。

## 插件审核要求

- `PLUGIN_METADATA` 必须是可由 AST 字面量读取的映射；
- 默认 `execution_mode: subprocess`；`in_process` 属于高风险申请，需说明不可替代性；
- `permissions`、`domains`、`input_files` 和依赖只声明实际需要的最小集合；响应正文权限
  `responses:payload` 必须与元数据读取分开说明；
- 调用新版宿主代理时声明 `required_capabilities`；使用持久状态时声明正整数
  `state_schema_version`，并说明迁移与留存策略；
- 市场界面只能使用 `view` 声明式组件。`resources:read`、`surfaces:background`、
  `render:local` 与 `render:scripted` 必须逐项说明；脚本渲染不能与静态快照合并成一个授权；
- 插件许可必须属于仓库允许的 SPDX 列表；
- `listing.md` 说明功能、数据去向、权限理由、兼容版本、许可和限制。

## 模板审核要求

模板与插件同步走整包签名、投稿、维护者复签、目录签名和更新规则。模板还必须：

- 使用安全可解析的 YAML，`template.id`、`template.version` 与签名 manifest 一致；
- `template.domains` 只写小写主机名，不含协议、路径或通配符；
- 固定 HTTP(S) seed 的主机必须被 `template.domains` 覆盖；
- 凭据只用 `secret://name` 引用，绝不提交明文；
- 对第三方数据源写明服务条款、频率限制、是否需要 API Key 和数据许可。

## DCO

所有 PR 中的提交必须包含 `Signed-off-by`。这表示你同意 Developer Certificate of Origin，
确认自己有权提交这些内容。GUI/CLI 只在你明确确认后自动加入 sign-off；也可手动使用：

```bash
git commit --signoff
```

## 维护者发布命令

外部 PR CI 不接触冷私钥。人工审核后，维护者在受控环境运行：

```bash
python tools/finalize_submission.py submissions/plugins/<fingerprint>/<id> \
  --reviewed-manifest-sha256 <人工核对的完整哈希> \
  --maintainer-key <冷存储私钥路径>
```

模板使用对应的 `submissions/templates/...` 路径。工具会验证投稿、保护作者归属和版本单调性、
复签整包、生成并签名 catalog、写透明日志，最后执行严格发布检查。
