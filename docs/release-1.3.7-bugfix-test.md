# TachiTalk v1.3.7 配置与语音修复测试版

测试包：[TachiTalk-v1.3.7-config-voice-bugfix-test-main.zip](../work/bugfix-20261024/delivery/TachiTalk-v1.3.7-config-voice-bugfix-test-main.zip)。大小77,484,153字节，SHA256 `089e61c135b97eb5852593d5685ef25e08c2edb1e39ce4bc676c866d28b3d622`。同目录有.sha256.txt。桌面复制被系统权限拒绝，原v1.3.6包未覆盖。

全部解压后运行TachiTalk_main_setup.exe，EXE/BIN保持同目录。独立Test AppId、默认TachiTalk-Test-1.3.7目录和快捷方式，不沿用日常安装目录；个人配置继续使用现有用户数据，请保留原文件。

- 已确认并修复：缺语音时临时文字降级覆盖自动朗读意愿，安装器误排除嵌套assets漏装开关/箭头图标，下载检测开始/完成两次跳滚；两处魔搭卡片统一为官网标识。
- 已验证：最终495项/498.672秒；真实Qt、真实Inno原生安装、独立冻结进程恢复、实际DPR100%/125%/150%和原控件四态；本机RTX4060原稳定环境真实TTS就绪/合成/默认播放（未开试听，LLM为确定性夹具）。相关冻结QA代码与产品相同，QA辅助exe不交付。
- 尚未证实解决：目标的BUG1神态错误映射、BUG4关闭重开恢复默认在隔离源码和冻结程序中未复现。保留已有用户映射，不自动清配置/迁移覆盖；需要目标的保存/恢复日志、非敏感mapping和实际EXE路径继续定位。
- 目标语音复测：核对“自动朗读回复”的明确选择，安装/重启后不先进入试听页，等待日志真正报告TTS就绪，再核对对话声音。旧版保存的false与用户主动关闭不可区分，不会强制开启。
- 未完成RTX5070 Laptop兼容验收、Windows10干净机或完整6.2GB下载安装验收。当前结果不能代替目标实机。

Cloudflare保持移除；GitHub至多3秒/1KiB、严格小于250ms选源、既有任务来源锁与缓存、手动切源先停再清当前任务、固定魔搭静默main feed及独立线程均保持。无正式Release/云端修改/信任链重建/语音环境升级。完整证据见[验证记录](release-1.3.6-bugfix-validation.md)与[证据目录](release-evidence-1.3.7-bugfix/README.md)。
