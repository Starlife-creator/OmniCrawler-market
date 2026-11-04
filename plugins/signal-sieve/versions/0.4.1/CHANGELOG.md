# 变更记录

## 0.4.1 — 2026-11-02

修复 HTML 实体恢复为 `<tag>` 后可能作为正文片段输出的问题；抽取正文在评分前移除标记尖括号，避免把属性或实体片段误报为文本。

## 0.4.0 — 2026-10-04

按 final_url、url、request.url 兼容取来源地址。质量评分结合结构、标点、链接与长度，抑制非正文重复词块；输出 quality 及评分依据。

mode: balanced / precision / recall；emit_diagnostics: true 可在空抽取时输出 extraction_diagnostic 记录，默认不生成。confidence 为启发式质量分数，不是成功概率。

零网络、零持久状态、无新增运行依赖。固定样本可回归，但不代表所有站点的抽取准确率。
