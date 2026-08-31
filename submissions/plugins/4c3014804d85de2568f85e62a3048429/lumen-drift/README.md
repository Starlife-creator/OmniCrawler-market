# Lumen Drift（流光漂移）

Lumen Drift 是一个仅供本地高信任安装的声明式 OmniCrawler UI 插件。插件本身只登记名称和
安全默认值；媒体扫描、控制面板、背景绘制和播放器生命周期全部由应用本体的 Background Host 管理。

## 当前能力

- 宿主读取用户明确选择的一个本地目录，最多检查 5,000 项、列出 500 个媒体文件；
- 支持 PNG、JPEG、WebP、BMP、GIF 以及 MP4、WebM、MOV、M4V、MKV、AVI；
- 支持覆盖裁剪、完整包含、拉伸、可见度、暗色遮罩、静音视频和定时轮播；
- 目录、显示参数和轮播间隔由宿主设置空间保存；
- 停用时立即停止播放器和轮播计时器。

## 有意不支持

- 不扫描整个磁盘、Steam 库或注册表；
- 不调用 Wallpaper Engine，不执行命令或打开网络连接；
- 不加载 HTML、JavaScript、Scene、Application 或 `.pkg` 壁纸；
- 不接受市场投稿。当前 OmniCrawler 市场禁止第三方 `ui` 插件。

## 本地开发加载

本插件是契约 1 `register(registry)` 原生 UI 插件，但不再提供 QWidget、绘制或播放器回调，
仅调用 `register_background(...)`。它仍属于本地 UI 扩展，不进入禁止第三方 UI 的公共市场。

## 设计来源与原创说明

产品方向借鉴动态壁纸插件的“媒体背景、可读性遮罩、轮播控制”方法论。代码、测试、文档和
素材均为独立实现，没有复制借鉴项目源代码。

## License

MIT
