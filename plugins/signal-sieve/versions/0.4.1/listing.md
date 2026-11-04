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
