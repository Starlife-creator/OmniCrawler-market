# 安全策略（OmniCrawler 插件生态）

## 信任模型

- **单信任根 ed25519**：签名用持有者冷存储的私钥生成（离线机），验签用随包分发
  的公钥（主仓库 `configs/plugin_trust.pub.pem` 与本目录 `keys/` 副本，内容相同）。
- **fail-closed**：应用加载插件前必须通过信任根验签；验签失败直接拒载，
  并在市场面板标记「不可信」。
- 贡献者无法自签：`plugin.py.sig` 只能由持有冷私钥的发布者在离线机器生成，
  签名即背书。

## 私钥红线

- 私钥只存在于离线冷存储介质（加密 U 盘 / 气隙机），**从不**进入：
  - 本目录（`.gitignore` 按 glob 拦截 `*.pem`、`*.key`、`.env` 等，公钥例外放行）；
  - 插件包、便携构建产物、CI 环境。
- 公钥无保密性要求：`keys/plugin_trust.pub.pem` 可随应用与生态分发。

## 发布前扫描

提交插件前必须运行发布前安全扫描：

```bash
python tools/scan_plugin.py scan plugins/<plugin_id>/
```

检查项：敏感扩展名/文件名黑名单、高熵字符串、API Token 模式、私钥字段、
（可选 `--manifest plugin.yaml`）允许列表外文件。

## 报告漏洞

- 插件本身的漏洞：请直接向该插件作者报告，并抄送生态维护者。
- 生态基础设施（签名/验签/索引）漏洞：**请勿公开**。通过 GitHub Private
  Vulnerability Reporting 提交（仓库 Settings → Security 已开启），处置披露
  期限 90 天：
  https://github.com/Starlife-creator/OmniCrawler-market/security/advisories/new
  若 PVR 不可用，可改用 zqx666666@tutamail.com 直接联系维护者。
- 报告时请包含：影响范围、复现步骤、受影响的插件/版本、修复建议。

## 密钥轮换与灾难恢复

- 密钥轮换：新公钥随应用发布内置，旧签名仍可验证。
- 灾难恢复：私钥采用 Shamir Secret Sharing 分片（N-of-M 恢复），分片各自独立保管。
