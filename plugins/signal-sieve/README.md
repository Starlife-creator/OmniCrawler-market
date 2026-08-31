# Signal Sieve（信号筛）

一个无网络、零第三方依赖的正文抽取插件。它综合文本长度、链接密度、标点连续性、语义标签、
模板噪声标记和 Article 类 JSON-LD，提供 `precision`、`balanced`、`recall` 三种模式。

输出包括正文、基础 Markdown、标题/作者/日期、粗粒度语言、字数、阅读时长、置信度、候选块与
降级原因。支持 `extractor.process` 与 `transformer.transform`；不下载网页，也不执行脚本。
方法论借鉴 Trafilatura 对精度/召回率和正文元数据的关注，代码完全独立实现。
