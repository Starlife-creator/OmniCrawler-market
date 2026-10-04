# Lumen Drift（lumen-drift）

版本：0.6.0 · 渲染生命周期、缩略预览与设置 · 2026-10-04。发行包使用现有作者身份签名；修改载荷后必须重新签名。

## 功能

先配置再启动 live，启动后 set 失败会停止新任务并清除无效背景。支持 HTML 禁脚本静态缩略预览（320×180，明确显示到背景）；快照句柄缓存最多 8 项，刷新与失败后清空。

## 配置与状态

新增 state:read/state:write 保存资源视觉偏好，schema 1，最多 256 项。按可选设置分组与资源相对身份保存，临时授权句柄不持久化；不同目录的同名资源可用不同分组。持久状态不可用时保留会话设置。

## 权限与数据去向

声明权限：resources:read, surfaces:background, render:local, render:scripted, state:read, state:write。resources:read 读取授权资源；surfaces:background 呈现背景；render:local 用于静态快照；render:scripted 用于隔离动态 HTML。宿主没有内嵌图片预览组件，因此缩略预览会替换当前背景；点击资源恢复完整播放。宿主单 live 会话，失败时不保证无闪烁恢复旧动态背景。手动暂停冻结展示，宿主仍可能生成帧，不承诺节能。系统自动暂停、多显示器和完整 Wallpaper Engine 运行不属于此版本。

## 兼容与许可

最低核心版本：0.12.0；执行模式：subprocess；许可：MIT。
