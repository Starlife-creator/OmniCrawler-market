# 数据质量校验

采集失败常常是**静默的**：站点改版后标题选择器失效，于是所有条目的 `title`
都是空串 —— 采集「成功」了 500 条，实际全是废数据。等你打开导出文件才发现，
已经跑了几十分钟。

这个插件在导出前做一遍质量检查，当场把问题报出来。

## 它检查三类问题

| 类别 | 判据 | 典型成因 |
|---|---|---|
| `missing` | 必填字段为空 | 选择器失效、站点改版 |
| `duplicates` | 稳定键重复 | 分页逻辑有误、去重没生效 |
| `suspicious` | 字段值像整段 HTML，或超长 | 抓错了层级、把 `<html>` 当标题 |

输出示例：

```json
{
  "total": 3,
  "missing": [{"index": 0, "fields": ["title"]}],
  "duplicates": ["sku-a"],
  "suspicious": [{"index": 2, "field": "title", "reason": "疑似整段 HTML"}],
  "counts": {"missing": 1, "duplicates": 1, "suspicious": 1},
  "ok": false,
  "fatal": true
}
```

## 配置

```yaml
plugins:
  validate-items:
    required: [title, url]      # 必填字段
    key_field: sku              # 稳定键，默认 "key"
    max_field_chars: 20000      # 超长判据
    fail_on: [missing]          # 哪些问题算致命，默认全部三类
```

`fail_on` 让你分级处理：例如只把「必填缺失」当致命，而「重复」只警告。

## 一个容易错的地方：`0` 和 `False` 不是空

价格 `0`、状态 `False` 都是**合法数据**。很多校验实现用 `if not value`
判断空，会把它们误判成缺失。本插件对 `bool` / `int` / `float` 单独处理，
只有 `None` / `""` / `[]` / `{}` 才算空。

## 边界

* **只报告，不修改数据** —— 是否丢弃条目由调用方按 `fatal` 决定。
* 纯函数、无 IO，`permissions: []`。
* 每个条目最多报一条 `suspicious`（避免同一行刷屏）。

## 许可

MIT。
