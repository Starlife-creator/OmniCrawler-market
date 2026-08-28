# 模板生态

模板是声明式 YAML，但分发安全边界与插件同步：创建完成即形成可私下分享的创作者签名包；
选择投稿后，市场静态审核并由维护者复签同一整包 manifest。模板不会因为“不是代码”而跳过
身份、凭据、域名、目录签名或更新保护。

## 创作者包

```text
template-folder/
├── template.yaml
├── listing.md
├── creator.identity
├── package.manifest.json
├── package.manifest.creator.sig
└── creator.sig                 # 旧客户端兼容轨
```

作者可直接分享这个文件夹。接收端先验证完整文件集合和创作者签名，再展示指纹、域名及配置
风险并请求确认。私下分享不会产生市场用户名，也不意味着市场审核。

## 投稿目录

应用或 CLI 将同一包放到：

```text
submissions/templates/<creator_fingerprint>/<template_id>/
```

并添加不在创作者签名范围内的 `submission.json`，仅用于投稿状态和市场展示请求。
外部 PR 不应直接改 `templates/`、`authors/` 或 `catalog.json`。

## YAML 约束

`template.yaml` 至少应包含：

```yaml
template:
  id: sites/example
  name: Example
  version: 1.0.0
  category: sites/general
  description: 示例模板
  domains: [api.example.org]
  min_core_version: 0.11.1
  license: 数据与服务条款说明
source:
  kind: rest
  seeds: [https://api.example.org/items]
```

- `template.id` 和 `template.version` 必须等于签名 manifest 中的值；
- `domains` 只接受小写主机名，固定 seed 主机必须被覆盖；
- API Key 等只写 `secret://name`，不能出现真实凭据；
- `listing.md` 说明数据来源、条款、配额、礼貌延迟、许可和用户需提供的参数。

## 正式发布布局

维护者发布工具保留创作者字节并添加维护者签名与市场 overlay：

```text
templates/<market-directory>/
├── market.yaml
├── template.yaml                     # 首个现代版本
├── package.manifest.*
└── versions/<new-version>/...         # 后续版本，不覆盖旧版
```

客户端先验证 `catalog.json.sig`，再下载 manifest 声明的全部文件，并同时验证创作者签名和
维护者签名。模板更新也要求同一作者指纹和严格递增 SemVer。
