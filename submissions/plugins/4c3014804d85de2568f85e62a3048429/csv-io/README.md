# csv-io · CSV 导出/导入

把采集结果导出成「Excel 与命令行都能正确打开」的 CSV。

## 解决的三个真实坑

### 1. Excel 打开中文 CSV 是乱码

Excel（Windows 中文版）默认按 **GBK** 打开 `.csv`，而 Python 写出的是 UTF-8 无 BOM ——
于是「商品名称」变成「鍟嗗搧鍚嶇О」。本插件写 **UTF-8 BOM**（`utf-8-sig`），
Excel 认 BOM，命令行工具（jq / python）也能正确跳过它。

### 2. 字段里的换行/逗号/引号破坏结构

正文常含换行。手写 `",".join()` 会直接把表格拆坏。这里走标准库 `csv` 的
`QUOTE_MINIMAL`，正确处理全部转义。

### 3. 公式注入

以 `=`、`+`、`-`、`@` 开头的单元格会被 Excel 当公式执行。
恶意站点的标题写 `=HYPERLINK("http://evil","click")` 就能在用户打开时外联。
默认加前缀 `'` 转义（可用 `sanitize=False` 关掉）。

## 操作

| operation | 方向 | 说明 |
|---|---|---|
| `exporter.csv` | 导出 | 条目列表 → CSV 文本 |
| `processor.csv-parse` | 导入 | CSV 文本 → 条目列表（自动容忍 BOM） |

## 权限与数据去向

**零权限**（`permissions: []`）。运行于隔离子进程，**不能 import omnicrawler**，
不读文件、不联网、无第三方依赖 —— 纯函数，返回文本，写文件由宿主负责。

## 兼容与许可

- OmniCrawler `>=0.7.0`
- MIT

## 已知限制

- 不做类型推断：所有单元格都是字符串（下游按需转换）。
- 超长单元格由宿主按 `excel_safe` 截断（Excel 单格上限 32767）。
