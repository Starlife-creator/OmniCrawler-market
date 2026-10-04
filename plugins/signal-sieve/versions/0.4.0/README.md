# Signal Sieve（signal-sieve）

版本：0.4.0 · 来源追溯与正文质量 · 2026-10-04。发行包使用现有作者身份签名；修改载荷后必须重新签名。

## 功能

按 final_url、url、request.url 兼容取来源地址。质量评分结合结构、标点、链接与长度，抑制非正文重复词块；输出 quality 及评分依据。

## 配置与状态

mode: balanced / precision / recall；emit_diagnostics: true 可在空抽取时输出 extraction_diagnostic 记录，默认不生成。confidence 为启发式质量分数，不是成功概率。

## 权限与数据去向

声明权限：无。零网络、零持久状态、无新增运行依赖。固定样本可回归，但不代表所有站点的抽取准确率。

## 兼容与许可

最低核心版本：0.11.2；执行模式：subprocess；许可：MIT。

## 历史使用参考

以下保留此前版本使用说明；旧版权限、版本和行为描述仅作历史参考，当前行为以本文上方说明为准。

# Signal Sieve（信号筛）

## 0.3.0 开发版（2026-10-03，待作者签名）

支持有界 JSON-LD @graph 遍历，父容器噪声与 article/main 语义继承到子块；标题不混入正文。编码按响应 charset、HTML charset、BOM 与 UTF-8/GB18030/Windows-1252 有序降级。中文字符独立计数，Markdown 支持列表、代码块和引用。

以上为当前行为；下文旧版本内容保留为历史说明。


一个无网络、零第三方依赖的正文抽取插件。它综合文本长度、链接密度、标点连续性、语义标签、
模板噪声标记和 Article 类 JSON-LD，提供 `precision`、`balanced`、`recall` 三种模式。

输出包括正文、基础 Markdown、标题/作者/日期、粗粒度语言、字数、阅读时长、置信度、候选块与
降级原因。支持 `extractor.process` 与 `transformer.transform`；不下载网页，也不执行脚本。
方法论借鉴 Trafilatura 对精度/召回率和正文元数据的关注，代码完全独立实现。
