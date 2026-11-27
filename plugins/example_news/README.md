# example_news · 契约 2 插件样板

**这不是一个真实站点适配器**，而是「怎么把契约 2 插件写对」的可运行样板。
复制这个目录即可开始写自己的站点适配器。

## 它做什么（同时也是最小可用形态）

`source.seed` 操作：把配置里的 `seeds` 转成待抓请求，并统一附加
`X-Requested-With: XMLHttpRequest`（某些站点只有带这个头才返回数据），
再打一个 `site` 标记便于下游区分来源。

## 契约 2 的四条硬规矩（本样板逐条示范）

| 规矩 | 样板里怎么体现 |
|---|---|
| **不能 import omnicrawler** | 全文件只有标准库；一切输入经 `payload` |
| `PLUGIN_METADATA` 必须是**静态字面量** | 直接写 dict，不能用变量拼 |
| 运行在**隔离子进程** | `execution_mode: subprocess`（默认且推荐）|
| 权限最小化 | `permissions: []` —— 本插件只产生请求描述，不联网 |

★ 还有一条不写在文件里但同样重要：**插件不自己发请求**。
它只返回「要发的请求描述」，由宿主经 `EgressBroker` 真正发出（审计 / robots /
预算都在那一层）。绕开这条边界就是违规。

## 怎么改成你自己的适配器

1. 复制整个目录，改 `id` / `name` / `description`；
2. 在 `handle` 里处理你的 `operation`（`source.seed` / `processor.*` / `exporter.*` …）；
3. 需要权限就往 `permissions` 里加**最小集合**，并写进 README 说明理由；
4. 加 `tests/`；
5. 用 `sign_plugin.py creator-sign` 签创作者身份，再走投稿流程。

## 权限与数据去向

**零权限**。只产生请求描述，不联网、不读文件、不碰凭据。

## 兼容与许可

- OmniCrawler `>=0.7.0` · MIT
