# document-workbench 的市场发布路径（核实记录）

> 记录时间：2026-11-17 · 背景：文档工作台从宿主迁为插件后，如何让用户下得到

## 结论先说

**契约 1（`in_process`）插件可以进市场。** 市场技术上完整支持它，
只是会**标注高风险**并在安装时走特权审批。

我一度判断"不能进市场"，那是**只读了文档措辞、没验证代码**的错误结论。
本文件记录实际核实过程，避免后人重复这个误判。

## 核实证据（四道技术环节都接受 in_process）

| 位置 | 实际行为 |
|---|---|
| `validate_submission.py:291` | `execution_mode` 合法值 = `("subprocess", "in_process")`，**不拒绝** |
| `catalog_lib/schema.py:55-63` | 注释原文：「in_process 是特权申请（3.2 批准矩阵运行期裁决，**catalog 侧只记录声明**）」 |
| `generate_discovery_page.py:171` | 风险分级：`in_process` ⇒ **high / 高风险**（这是警示，不是拒绝） |
| `generate_discovery_page.py:181-182` | 展示给用户的理由：「执行模式为 in_process（进程内运行）」 |

实测调用：

```
$ python -c "from generate_discovery_page import _permission_risk; ..."
风险等级: ('high', '高风险')
风险说明: 执行模式为 in_process（进程内运行）
```

## 文档措辞与实际实现的差别

`docs/PLUGIN_CONTRACT.md:13` 写：

> 契约 1（本地特权）… 仅供明确受信任的本地扩展；**不接受公共市场投稿**

**这句是政策建议，不是代码拦截。** 代码里没有任何一处拒绝 `in_process`。

两者的真实关系是：

- 市场**可以收录**，但会：
  - 标为高风险；
  - 安装时要求用户逐项确认（`plugin_market_logic._permission_risk` 同一判据）；
  - 运行期还要过一次批准矩阵（`plugins.in_process_allowlist` + `expires`）。
- 所以"进市场"与"用户能装"是两件事：前者靠签名，后者靠审批。

## 发布需要产物

`creator-sign`（`tools/sign_plugin.py`）会自动生成 4 个文件，
**不需要手写**：

| 文件 | 作用 |
|---|---|
| `creator.identity` | 创作者公钥指纹 |
| `package.manifest.json` | 全部文件的 sha256 清单 |
| `creator.sig`（`package.manifest.creator.sig`） | 包签名 |
| `plugin.py.sig` | 单文件兼容签名 |

命令（需维护者身份密码，**不由 AI 代输**）：

```powershell
cd E:\tool\biancheng\omnicrawler\OmniCrawler
$env:OMNICRAWL_IDENTITY_PASSWORD = "<你的密码>"
.\.venv\Scripts\python.exe tools\sign_plugin.py creator-sign `
    "E:\tool\biancheng\omnicrawler\OmniCrawler-market\submissions\plugins\4c3014804d85de2568f85e62a3048429\document-workbench" `
    --username starlife --skip-scan
```

## 签名前的核查（已完成）

- **入包文件 152 个，无测试残留**。`_payload_files` 会排除
  `__pycache__` / `.pytest_cache` / `.git` 等（`_IGNORED_PARTS`），
  但**不排除** `pytest-of-*` / `tmp*`——所以测试临时目录未被清掉时
  会被打进 manifest。已确认当前目录干净。
- `plugin.yaml` 字段与另外 8 个投稿对齐，`plugin_types`（processor/exporter）
  与 `license`（Apache-2.0）均在白名单内。
- `permissions: []`——契约 1 不需要声明权限。

## 仍未完成

- 插件**未签名**（需要身份密码）；
- 签名后还需把目录从 `submissions/` 移到 `plugins/<fingerprint>/document-workbench/versions/<ver>/`，
  才会进 `catalog.json`（用户能在市场里搜到）；
- 真机安装验证（`plugins_installed/` 三层布局 + 审批）尚未在可见桌面环境跑过。
