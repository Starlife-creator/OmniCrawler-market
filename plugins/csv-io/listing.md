# CSV 导出/导入

标准库 `csv` 完全够用 —— 但爬虫导出的 CSV 有三个真实坑，这个插件把它们
一次性处理掉。

## 坑 1：Excel 打开中文 CSV 是乱码

Excel（Windows 中文版）默认按 **GBK** 打开 `.csv`，而 Python 写出的是
UTF-8 无 BOM —— 于是「商品名称」变成「鍟嗗搧鍚嶇О」。

**修法：写 UTF-8 BOM**。Excel 认 BOM，命令行工具（`jq` / Python / DuckDB）
也能正确跳过它。这是「同一个文件既要给 Excel 又要给脚本」的唯一解。

```json
{"text": "\ufeff名称,价格\r\n机械键盘,199\r\n", "count": 1, "fields": ["名称","价格"]}
```

## 坑 2：字段里的换行/逗号破坏结构

正文常含换行。手写 `",".join()` 会直接把表格拆坏。这里走标准库的
`DictWriter`（`QUOTE_MINIMAL`），换行与逗号都被正确引用。

实测往返：`"第一行\n第二行，含逗号"` 写入再读回，内容**完全一致**。

## 坑 3：公式注入

以 `=`、`+`、`-`、`@` 开头的单元格会被 Excel 当公式执行。恶意站点的标题
写 `=HYPERLINK("http://evil","click")`，用户一打开表格就外联。

默认加 `'` 前缀转义；确知数据可信时可 `sanitize: false` 关掉。

## 配置

```yaml
plugins:
  csv-io:
    bom: true           # 默认 true（Excel 兼容）
    sanitize: true      # 默认 true（防公式注入）
    fields: [标题, 价格]  # 可选：显式指定列与顺序
```

## 两个操作

| 操作 | 载荷 | 返回 |
|---|---|---|
| `exporter.csv` | `{items}` | `{text, count, fields}` |
| `processor.csv-parse` | `{text}` | `{items, fields}` |

## 细节取舍

* **列顺序按首次出现**（不是字母序）—— 保持稳定，便于 `diff` 两份导出；
* **行尾用 `\r\n`** —— RFC 4180 的要求，Excel 与多数工具都期望它；
* 解析时 `lstrip("\ufeff")` 容忍 BOM。

## 边界

纯函数、无 IO —— 返回文本，写文件由宿主负责（`permissions: []`）。
只用标准库，零第三方依赖。

## 许可

MIT。
