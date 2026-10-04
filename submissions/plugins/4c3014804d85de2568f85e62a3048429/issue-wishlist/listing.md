# issue-wishlist（issue-wishlist）

版本：1.2.0 · 更新时间排序与用户标记 · 2026-10-04。发行包使用现有作者身份签名；修改载荷后必须重新签名。

## 功能

保留每条 issue 的 created_at/updated_at，按最近更新或创建排序。支持收藏、已读、收藏列表与未读筛选，刷新失败保留旧列表。

## 配置与状态

新增 state:read/state:write 用于按仓库与 issue 编号保存布尔标记，schema 1，最多 1000 项，超限淘汰最早标记。不可用时仅保留会话标记并明确提示。状态不存 issue 正文、凭据或本机路径。

## 权限与数据去向

声明权限：network:scoped, state:read, state:write。network:scoped 仅访问 api.github.com 公开只读接口，仍只查询开放 Issues；不投票、不评论、不创建远端条目。无自动轮询；30 秒刷新间隔、403/429 至少等待 60 秒。

## 兼容与许可

最低核心版本：0.14.0；执行模式：subprocess；许可：MIT。
