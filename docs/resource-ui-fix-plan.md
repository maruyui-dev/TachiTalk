# 资源面板与检查误报修复（2026-10-23）

用户已授权实施审核图中的 UI、修复检查逻辑并交付主程序供 GitHub 下载实测。用户确认尚未开始安装语音，本轮不能声称用户网络下安装成功。

1. 更新检查：先使用经过结构验证的 Release 版本与附件名，区分当前最新版、有新版本但无适用补丁、版本未知、真实网络/验签失败。API 失败仍尝试附件签名清单。安装只信任签名清单，版本 API 不能授权文件操作。
2. 界面：嵌入现有主控制面板，沿用猫咪与浅粉配色；主程序、语音、磁盘、下载、安装位置和下载设置分区。真实磁盘容量圆环与下载水平进度分离；未知数据明确显示尚未读取。新语音固定安装到主程序 services/gpt_sovits，旧语音复用入口单列。
3. 下载操作：保留验签、分卷哈希、断点/ETag 校验、暂停/取消保留缓存和离线导入；提供可用来源选择，切换活动下载时先停止旧任务再重启。缓存跨来源是否能续传由服务端标识校验决定。
4. 验证与交付：RED/GREEN 回归、现有全套测试、实际 Qt 截图、小流量匿名 GitHub 验签及 HTTP 下载/续传；仅构建主程序，不复制语音环境。使用新文件名交付测试版；保留已发布 1.3.0、稳定标签、安装程序和现有工作区。

备份：work/ui-resource-fix-20261023/before 保存本次拟修改文件的原内容；git-before.txt 保存原工作区列表。详细完成证据更新到 IMPLEMENTATION_STATUS.md。

实现依据：[GitHub Release API](https://docs.github.com/en/rest/releases/releases)、[Qt QStackedWidget](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QStackedWidget.html)、[Qt QPainter](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QPainter.html)。
