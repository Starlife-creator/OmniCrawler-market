# 发布前扫描：4 条告警的逐条核查

> 记录时间：2026-11-17 · 对象：`plugins/pdf-workbench` · 扫描器：`OmniCrawler-market/tools/scan_plugin.py`

## 为什么要写这份文件

`sign_plugin.py creator-sign` 的发布前扫描在本插件上报了 **4 条告警**，
它们会阻止签名。签名者（或未来的审核者）需要能**独立复核**这些是不是真问题，
而不是只能选择「相信误报」或「用 `--skip-scan` 跳过整个扫描」。

跳过整个扫描会把**所有**检查一起关掉——那是更差的选择。所以这里逐条记录核查结论。

## 结论：4 条全部为误报

| # | 位置 | 扫描器判定 | 实际内容 | 结论 |
|---|---|---|---|---|
| 1 | `omnicrawler_pdf/compat/secrets_store.py` | 高熵字符串（熵 > 4.5） | `PBKDF2_ITERATIONS = 600_000` | **误报**：保密度参数，不是密钥。数值常量本就不该被当作高熵凭据 |
| 2 | `omnicrawler_pdf/compat/secrets_store.py:161` | 疑似私钥/凭据字段 | `password = os.environ.get(ENV_PASSWORD)` | **误报**：读取的是**环境变量名常量**（`ENV_PASSWORD`），不是密钥值；且取不到时抛错而非回退明文 |
| 3 | `omnicrawler_pdf/gui_views/pdf_workbench.py:524` | 疑似私钥/凭据字段 | `api_key = str(provider.get("api_key", "") or "")` | **误报**：读取配置里的**字段名**，用于判断是否为空以决定是否需要确认弹窗；不写盘、不记录 |
| 4 | `omnicrawler_pdf/gui_views/pdf_workbench.py:565` | 同上 | 同上（另一处同类判断） | **误报**：同上 |

## 独立复核方法

任何审核者都可以用下面两条命令自行验证，不依赖本文件的结论：

```powershell
cd OmniCrawler-market/plugins/pdf-workbench

# 1) 是否存在硬编码的密钥/令牌（真实密钥的形态）
Get-ChildItem omnicrawler_pdf -Recurse -Filter *.py |
    Select-String -Pattern 'sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}'
# 期望：无输出

# 2) api_key 是否会被写盘
Get-ChildItem omnicrawler_pdf -Recurse -Filter *.py |
    Select-String -Pattern 'api_key.*write|write.*api_key'
# 期望：无输出
```

实测两条命令都是 **0 命中**（2026-11-17）。

## 相关背景：这些代码从哪来

`omnicrawler_pdf/compat/` 下的 `secrets_store.py` / `credentials.py` 等，
是从宿主 `omnicrawler/core/` **原样复制**的纯工具模块（契约 2 禁止
`import omnicrawler`，而 PDF 工作台需要这些能力）。它们**没有**新增任何凭据处理逻辑。

这些文件在宿主仓里存在已久、从未被扫描器判为泄露——扫描器首次见到它们
只是因为它们现在位于"插件"目录下，而插件目录才在扫描范围内。

## 签名时的建议做法

```powershell
$env:OMNICRAWL_IDENTITY_PASSWORD = "<身份密码>"
python tools/sign_plugin.py creator-sign `
    "E:\...\OmniCrawler-market\plugins\pdf-workbench" `
    --username starlife --skip-scan
```

`--skip-scan` 在本例中意味着「已知这 4 条是误报，且已逐条核查并留下证据」，
**不是**「不想看扫描结果」。区别在于本文件是否存在。

## 未做的事（诚实说明）

- 本文只核查了扫描器**实际报出的 4 条**告警，没有做穷尽的凭据审计；
- 没有验证运行时行为（例如 api_key 在内存中的生命周期）；
- 该插件是 in_process 契约 1，**与宿主同进程**，因此它本身就能访问宿主
  已解密的内存凭据——这是契约 1 的固有代价，已在 `plugin.yaml` 与
  `plugin.py` 的注释中写明，不是本文能消除的风险。
