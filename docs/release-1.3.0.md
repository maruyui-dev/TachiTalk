# v1.3.0 正式发布交接

## 本地交付目录

`D:\TachiTalk\work\production-release-1.3.0\upload` 是本次公开附件的唯一汇总目录。
`upload-assets.json` 位于其上一层，记录附件名称、长度、SHA-256 和 `uploaded: false`。
这表示仅完成本地准备，没有推送代码、创建 Release 或上传附件。

实际附件共12项，约10.20 GiB：主程序ZIP 77,936,741字节，完整离线EXE+3个BIN共4,647,572,386字节，语音4分卷6,219,221,474字节，另有签名清单/说明/校验表。

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

没有读取或保存 GitHub Token，不需要给客户端配置 Token；正式签名私钥与密码不进入本目录或客户端。

## 后续小版本

`work/production-release-1.3.0/main-1.3.0-inventory.json` 是正式 1.3.0 客户端基线，须与其对应构建一起安全保留。
下一版先修改版本并构建主程序，再用 `component_release.py --component main --base-version 1.3.0 --base-inventory <此文件>` 生成文件差异包并正式签名。
首次 1.3.0 不制造同版本补丁；旧 0.2.0 用户使用主程序安装器迁移，选择原安装目录并复用已有语音环境。

被标记为 latest 的后续主程序 Release 应附适用于仍支持基线的 `main-from-<基线>.json` 和有效的 `voice-manifest.json`。
语音未变时，原样沿用现有签名清单和指向旧 Release 的分卷 URL，无需再次上传或下载语音环境。

## 空间与证据

本次已获授权清理两套旧 QA 根中的重复安装、ZIP、暂存和事务备份；JSON、截图、清单、trust 配置保留。
可复用的最新语音分卷已逐个及合并验证后同盘移动到正式发布流程，不重复压缩。
清理日志与逐项结果在 `work/cleanup-20261023/result.json`，测试与签名证据见 `IMPLEMENTATION_STATUS.md`。
已有 `dist`、`build`、原始 `services`、用户配置/角色资源、`.git` 和生产密钥未清理。

本次正式编译新增的 `work/production-release-1.3.0/build-offline/voice-stage` 约9.4 GiB。工具自动审批拒绝了其删除（仅返回 `blocked by policy`，无详细原因），故暂存仍在；它不在upload目录，可在资源管理器手动删除，不影响公开附件。最终D盘可用165.53 GiB，较清理开始净增加79.58 GiB（已计入正式发布文件和该暂存）。

当前验证范围以最新状态记录为准。此前独立语音安装/实际GPU推理/卸载全链已经实测；本次正式公钥构建另做核心UI、正常启动关闭和原生更新器签名/坏包拒绝测试。
Windows10/RTX50/干净系统、真实GitHub与公共代理、正式完整离线包的再次实机安装仍需另行验收。
