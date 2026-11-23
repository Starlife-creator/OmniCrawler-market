# 变更对比报告

增量采集时，用户真正想知道的不是「一共 500 条」，而是**这次比上次变了什么**：
有 3 条新增、1 条改价、2 条下架。

这个插件把两次采集结果对比成三类差异，输出可读摘要 + 结构化数据。

## 它做什么

给定 `previous` 与 `current` 两组条目（各带稳定键），产出：

```json
{
  "added": ["sku-101", "sku-102"],
  "removed": ["sku-088"],
  "changed": [
    {"key": "sku-093", "fields": ["price"]}
  ],
  "counts": {"previous": 50, "current": 51, "added": 2, "removed": 1, "changed": 1},
  "summary": "对比完成：新增 2、删除 1、修改 1（前 50 → 现 51）"
}
```

`changed` 里只报**哪些字段变了**，不整条回传 —— 报告要能一眼读完。

## 配置

```yaml
plugins:
  diff-report:
    key_field: sku          # 稳定键字段名，默认 "key"
    ignore:                 # 不参与比较的字段
      - fetched_at          # 每次采集都变
      - etag
```

### `ignore` 为什么必要

不加 `ignore`，`fetched_at` 这类「每次采集都会更新」的字段会让**所有条目**
都报「修改」，报告就失去意义。实测：同两组数据，`ignore: [fetched_at]` 时
报 1 条修改，不 ignore 时报 2 条（多出来的那条其实没变）。

## 边界

* **纯函数、无 IO**：输入来自 payload，输出是纯数据结构，便于完全单测覆盖。
* **不碰网络、不碰文件系统**：`permissions: []`。
* 没有稳定键的条目会被跳过（无法对比），不计入 `counts`。

## 许可

MIT。
