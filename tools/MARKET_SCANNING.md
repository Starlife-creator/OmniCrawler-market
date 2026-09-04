# 多版本市场安全扫描

本地发布预检与 CI 均执行 `python tools/scan_market.py --registry <市场目录>`，
并独立执行 `python tools/generate_catalog.py --publish-check`。凭据扫描不替代签名验证。

根目录旧包与 `versions/<版本>/` 新包分别使用各自清单扫描。旧包扫描使用临时副本，
不修改原始包或签名字节；只拆分市场根级的版本容器，不改变普通扫描器的递归规则。
所有历史版本也参与扫描，不仅检查 catalog 当前选中的版本。

版本容器中的散落文件、缺少清单或入口的版本、版本号与目录不符、空版本容器、
符号链接或目录联接均拒绝。旧包不得把保留的 `versions/` 路径声明为自身载荷。
版本包内部额外文件仍由原有允许列表门禁检查，说明文档仍检查凭据内容。

运行 `python tools/check_scan_market.py` 和 `python tools/check_scan_plugin.py`
执行扫描回归检查。修改扫描规则不需要重新签名未变更的插件包。
