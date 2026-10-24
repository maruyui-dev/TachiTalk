# v1.3.4 Cloudflare 下载与静默更新验证版

用户反馈 GitHub 不可达且原 Cloudflare 配置仍有问题。本版把新旧用户的默认来源迁移到 R2 直连域 `download.jieyiblog.me`，版本查询、语音清单和分卷都可走 Cloudflare；不再要求先连通 GitHub。

启动后保持原功能页可用，上次停在下载页则回到角色控制，版本检查在线程里静默执行。发现更高版本才提醒：签名增量包沿用验签更新器；完整安装包通过弹窗下载并手动解压安装。当前线上稳定版仍是 v1.3.0，测试包 v1.3.4 不会伪造线上新版提醒。

新用户所有神态下拉默认自动匹配；已保存的个人映射保留。源码运行状态与开发者资源 JSON 隔离，安装包不包含开发者映射。新配置启用后备公共代理，关闭公共代理不会关闭 Cloudflare。稳定语音环境未更换，自动选设备保留；torch2.7.1+cu128 包含 sm_120，RTX50 实机仍待测试。

## 下载

- [Cloudflare 测试主程序](https://download.jieyiblog.me/testing/v1.3.4/TachiTalk-v1.3.4-cloudflare-test-main.zip)
- 桌面：`D:/桌面/TachiTalk-v1.3.4-cloudflare-test-main.zip`
- 大小：77,986,366字节。
- SHA256：`70bd93f549074afeb2c1b23662df4609a9319a43749937d169adcb73634116b1`。
- 完整解压后运行 setup，EXE/BIN 必须在同目录；建议新测试目录。

正式 v1.3.0 原主程序安装包也已镜像到 `https://download.jieyiblog.me/v1.3.0/TachiTalk-v1.3.0-main.zip`，其原 SHA256 未变。测试对象放在独立 testing 路径，没有更新正式版本指针或 GitHub Release。

## 验证

- 全量413项通过417.069秒；此后调整一处检测取消/失败状态和静态文案，最终相关67项通过30.679秒。未将早先全量结果冒充最后调整后的再次全量。
- 最终冻结主程序隔离安装/真实Qt核心检查通过，全部神态下拉自动；无语音环境时文字、立绘、气泡可用。安装验收使用独立用户数据和安装目录，不替换日常安装。
- 冻结包公钥/来源与源码一致；无语音环境、开发者资源JSON或Cloudflare凭据。原生验收与ZIP所含最终程序字节一致，冻结PYZ包含 R2 映射。
- Cloudflare-only实际检查、生产语音签名、两个分卷206范围通过；正式主程序及新测试ZIP均从Cloudflare完整下载验 SHA；测试包桌面哈希一致。版本指针 no-store。
- 没有做完整语音下载/安装、全部用户网络免代理或 RTX50 实机合成验收。没有改变系统代理、DNS、Worker、稳定环境或公开 Git 历史/标签。

证据目录 `docs/release-evidence-1.3.4-cloudflare`；精确基线 `packaging/baselines/main-1.3.4-cloudflare-test-inventory.json`；后续 R2 发布顺序见 `docs/cloudflare-downloads.md`。弹窗设计与真实Qt截图均为明示设计示例，不代表 v1.3.5 已发布。
