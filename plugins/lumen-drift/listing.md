# Lumen Drift

在 OmniCrawler 工作台中浏览并呈现用户明确授权的本地图片、GIF、视频、本地 HTML，
以及 Wallpaper Engine 创意工坊目录中的受支持资源。插件提供自动发现 Steam App ID
`431960` 对应创意工坊目录和手动选择目录两个同等级入口；自动发现仍需用户主动点击。

## 安全与数据流

插件以契约 2 隔离子进程运行，只接收会话级不透明资源句柄，不接收宿主绝对路径。
目录枚举和文件读取由宿主执行；图片、GIF、视频、HTML 渲染及背景表面也全部由宿主控制。
插件不申请网络域名，不上传文件、目录信息或使用情况，也不包含第三方运行依赖。

本地 HTML 默认禁用脚本、断开网络并输出静态 PNG 快照。用户主动选择“隔离动态背景”后，
宿主才启动受限脚本帧流；仍禁止外部网络、下载、Service Worker、WebSocket、EventSource、
WebRTC 和 `sendBeacon`，并限制为单插件单流、最高 5 FPS、最高 1920×1080。

## 权限理由

- `resources:read`：枚举和读取用户明确授权目录句柄内的资源。
- `surfaces:background`：请求宿主管理的背景表面；插件不能注入 QWidget 或自定义绘制代码。
- `render:local`：将本地 HTML 以禁用脚本的断网静态快照呈现。
- `render:scripted`：仅为用户主动选择的隔离动态 HTML 帧流使用；不授予网络访问。

## 兼容性与限制

需要支持 `resource_provider`、声明式 `view`、资源句柄、本地 HTML 渲染和宿主背景表面的
OmniCrawler。宿主会在安装或启用前校验 `required_capabilities`；旧客户端将安全阻止运行。
Scene `.pkg`、程序型壁纸、外部网络资源和需要 Wallpaper Engine 私有运行时的效果不会执行。
未安装 Wallpaper Engine 或找不到创意工坊目录时会提示用户改用手动目录。

本插件实现完全原创，以 MIT 许可证公开。
