# Signal Sieve（信号筛）

## 0.3.0 开发版（2026-10-03，待作者签名）

支持有界 JSON-LD @graph 遍历，父容器噪声与 article/main 语义继承到子块；标题不混入正文。编码按响应 charset、HTML charset、BOM 与 UTF-8/GB18030/Windows-1252 有序降级。中文字符独立计数，Markdown 支持列表、代码块和引用。

以上为当前行为；下文旧版本内容保留为历史说明。


一个无网络、零第三方依赖的正文抽取插件。它综合文本长度、链接密度、标点连续性、语义标签、
模板噪声标记和 Article 类 JSON-LD，提供 `precision`、`balanced`、`recall` 三种模式。

输出包括正文、基础 Markdown、标题/作者/日期、粗粒度语言、字数、阅读时长、置信度、候选块与
降级原因。支持 `extractor.process` 与 `transformer.transform`；不下载网页，也不执行脚本。
方法论借鉴 Trafilatura 对精度/召回率和正文元数据的关注，代码完全独立实现。
