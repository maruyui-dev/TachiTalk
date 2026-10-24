# v1.3.0 正式发布交接

## 正式发布与本地交付

正式发布：[v1.3.0](https://github.com/maruyui-dev/TachiTalk/releases/tag/v1.3.0)。
公开源码 main 和 v1.3.0 标签均指向 `72f55799ecd7fd4e5a67f2236b1c0f17246bad32`。
12个附件均已上传，GitHub服务器的大小、SHA-256与本地发布清单一致；公开下载的签名清单已用生产公钥验证。
最终公开验收收据为 `docs/release-evidence-1.3.0/github-public-verification.json`。
此前准备阶段的 `upload-assets.json` 中 `uploaded: false` 是历史快照，发布状态以最终验收收据为准。

实际附件共12项，约10.20 GiB：主程序ZIP 77,939,279字节，完整离线EXE+3个BIN共4,647,678,016字节，语音4分卷6,219,221,474字节，另有签名清单/说明/校验表。
桌面保留 `D:\桌面\TachiTalk-v1.3.0-main.zip`，SHA-256 为 `d8c45415b858034f8bb31e2df7cd1a003e8f2a6d2c040a69078ed6218e4a7421`。
解压后运行 `TachiTalk_main_setup.exe`，EXE与BIN必须在同一目录。

附件用途：

- `TachiTalk-v1.3.0-main.zip`：仅主程序安装器及其 BIN，完整解压后运行 EXE。
- `TachiTalk_setup.exe` 与全部 `TachiTalk_setup-*.bin`：完整离线安装文件，全部下载到同一目录再安装。
- `voice-v2ProPlus-cu128-runtime-1.zip.part000` 至 `part003`：独立可选语音资源；保持原文件名。
- `voice-manifest.json`：维护者用原生产私钥签发，客户端 `release-1` 公钥已实际验证通过。
- `SHA256SUMS.txt`、`INSTALL.txt`：公开校验表和安装说明。

## GitHub 操作

1. 维护者准备 `maruyui-dev/TachiTalk` 的 `v1.3.0` Release 草稿。若该标签或 Release 已存在，先人工核对，不能覆盖既有稳定标签或远端资源。
2. 上传 `upload` 目录的全部附件。语音清单中的 URL 指向 `releases/download/v1.3.0/<分卷名称>`，标签与名称必须一致。
3. 核对 SHA-256、完整分卷、完整离线 BIN 和签名清单均在草稿中，再决定发布。不能只上传 EXE 或部分分卷。
4. 发布后进行真实 GitHub/代理下载与断点续传验收。本地模拟源与已有分卷验签不能替代线上实测。

发布工具通过现有Git凭据在进程内完成认证，未打印或保存Token；客户端使用公开资源，不需要Token。正式签名私钥与密码不进入本目录或客户端。

## 后续小版本

`packaging/baselines/main-1.3.0-inventory.json` 是正式 1.3.0 客户端基线；语音基线也保留在同目录。未来需要的正式构建可从本次Release下载，构建副本按用户要求清理。
下一版先修改版本并构建主程序，再用 `component_release.py --component main --base-version 1.3.0 --base-inventory <此文件>` 生成文件差异包并正式签名。
首次 1.3.0 不制造同版本补丁；旧 0.2.0 用户使用主程序安装器迁移，选择原安装目录并复用已有语音环境。

被标记为 latest 的后续主程序 Release 应附适用于仍支持基线的 `main-from-<基线>.json` 和有效的 `voice-manifest.json`。
语音未变时，原样沿用现有签名清单和指向旧 Release 的分卷 URL，无需再次上传或下载语音环境。

## 空间与证据

在公开Release验收通过后，按用户明确授权清理dist/build/scratch/work、重复备份、旧桌面安装包及指定缓存。必要的JSON测试证据、基线清单和完整回归日志已归档到项目 `docs/release-evidence-1.3.0`，不依赖清理目录。
保留原始services、独立GPT-SoVITS、用户配置/角色资源、.git/.venv、生产密钥，以及用户指定的Promo、PV、acl-recovery三个其他项目。
最终清理实测结果见 `docs/release-evidence-1.3.0/cleanup-result.json`；删除失败的具体文件名及完整路径见桌面 `TachiTalk-清理未完成明细.csv`。旧的暂存删除拒绝属于历史记录，当前是否仍残留以最终清单为准。

当前验证范围以最新状态记录为准。此前独立语音安装/实际GPU推理/卸载全链已经实测；本次正式公钥构建另做核心UI、正常启动关闭和原生更新器签名/坏包拒绝测试。
公开源码完整回归347项通过（364.268秒）；真实GitHub匿名附件下载、生产清单验签、暂停后两次HTTP206续传已通过，小流量仅约3.2MB，没有再次完整下载2GB分卷。匿名API首次曾限流，原命令重跑成功，证据保留。
Windows10/RTX50/干净系统、公共代理实际大文件可用性、真实断电、正式完整离线包的再次实机安装仍需另行验收。
