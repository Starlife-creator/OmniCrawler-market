# JSONL 导出

把采集结果导出成 **JSON Lines**：每行一条独立 JSON。

```
{"id":1,"title":"标题一"}
{"id":2,"title":"标题二"}
```

## 为什么用 JSONL 而不是一个大 JSON 数组

| | JSON 数组 | JSON Lines |
|---|---|---|
| 流式处理 | 要读完整个文件才能解析 | 逐行读，随时中断 |
| 大结果集 | 整个数组进内存，容易 OOM | 一行一条，内存恒定 |
| 手工查看 | 需要格式化工具 | `head -3` 就能看 |
| 下游工具 | 要专门解析 | `jq` / DuckDB / Spark 直接读 |

## 输出

| 字段 | 含义 |
|---|---|
| `text` | 完整 JSONL 内容（末尾带换行） |
| `count` | 实际写出的行数 |
| `skipped` | 因超长被跳过的条目数 |
| `media_type` | `application/x-ndjson` |
| `extension` | `jsonl` |

### 超长行会被跳过，且如实回报

单行超过 `max_line_bytes`（默认 1 MiB）的条目不写出，但**计入 `skipped`**——
不静默丢弃。超长往往意味着上游把整个 HTML 页面当成了字段值。

## 配置

```yaml
plugins:
  export-jsonl:
    max_line_bytes: 1048576   # 默认 1 MiB
```

## 细节

* **中文原样输出**（`ensure_ascii=False`）：文件更小、可读性更好。
  JSONL 规范要求 UTF-8，下游按 UTF-8 读即可。
* **紧凑分隔符**（`,` `:` 后无空格）：进一步减小体积。

## 边界

纯函数、无 IO。**不写文件**——写盘由宿主负责，插件只产生文本内容
（所以 `permissions: []`，不碰文件系统）。

## 许可

MIT。
