# Upstream Lantern

Upstream Lantern（上游灯塔）是一个独立的 OmniCrawler 契约 2 源插件。它把用户明确配置的
GitHub 仓库转换为有限、可审查的 `api.github.com` 只读请求，用于观察发布、标签、提交、
社区健康度、GitHub Actions 和指定软件包的 Reviewed 安全公告。

本插件不直接联网，不执行下载内容，不读取本地文件，不包含第三方依赖，运行权限声明为空。
完整功能、配置示例、安全边界、认证方式和已知限制见 [listing.md](listing.md)。

## 当前状态

版本：`0.1.0`。许可：MIT。

在生成 `creator.identity`、`package.manifest.json` 和
`package.manifest.creator.sig` 之前，本目录只是未签名开发包，不应作为可信插件分发。
创作者整包签名完成后，它既可以直接私下分享，也可以原样投稿 OmniCrawler 市场。

无论采用哪种分发方式，都不要在目录中放入 Token、Cookie、私钥、`.env` 或真实配置文件。
