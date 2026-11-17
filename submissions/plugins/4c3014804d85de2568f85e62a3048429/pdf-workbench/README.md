# PDF Workbench

十万级 PDF 结构化数据抽取工作台：摄取 → 解析 → OCR → 字段抽取 → 人工复核 → 五表导出。

## 这是什么

原本内置在 OmniCrawler 宿主里的 PDF 工作台，现在是**可选插件**。

装它，宿主多出完整的 PDF 工作台（与内置版功能一致）；
不装它，宿主只保留「爬虫+AI」与「插件市场」两条主线，启动更快、体积更小，
且不会看到一个空荡荡的 PDF 界面——因为入口根本不会出现。

## 能力

| operation | 作用 |
|---|---|
| `processor.process` | 摄取 / 解析 / OCR / 抽取 / 复核主流程 |
| `exporter.export` | 五表导出（xlsx / csv / markdown） |
| `pdf.validate` | 校验 PDF 项目配置（schema 级） |
| `pdf.status` | 查询项目数据库状态 |
| `pdf.apply_review` | 应用人工复核决定 |
| `pdf.selfcheck` | 插件自检：报告缺失的必需/可选依赖 |

## 依赖

**必需**：`pypdf`、`PyYAML`（随宿主提供）

**可选**（按用途，缺哪个只影响对应功能）：

| 模块 | 缺少时的影响 |
|---|---|
| `pypdfium2` | 无法渲染页面（OCR 需要） |
| `pdfplumber` | 无法提取 PDF 文字层 |
| `openpyxl` | 无法导出 Excel（CSV 仍可用） |
| `reportlab` | 无法写出 PDF |
| `paddleocr` / `pytesseract` | 对应 OCR 引擎不可用 |

随时可用 `pdf.selfcheck` 查看当前缺什么。

## 权限说明

| 权限 | 为什么需要 |
|---|---|
| `component:ocr` | 调用**已验签**的 OCR 组件。注意：验签、租赁锁、组件进程启动**全部由宿主执行**，本插件看不到信任根、组件路径与注册表 |
| `network:scoped` | LLM 字段抽取需要访问所声明的域名，全部经宿主 `network.fetch` 代理，插件不直连 |

## 与宿主内置版的关系

功能的**行为完全一致**：同一套 `pdfx` 代码、同样的数据库 schema、
同样的五表导出格式、同样的依赖指纹。

差别只在**运行位置**：插件跑在宿主启动的子进程里（契约 2），
所以它能单独安装、单独升级、单独卸载，而不影响宿主本体。

## 数据在哪

PDF 项目的 `work/` / `data/` / `output/` 由**项目配置**决定，
与本插件无关——卸载插件不会删除你的项目数据。
