# 2026-10-26 正式版 v2.0.0 r7：语音安装长路径修复

## 用户报错与确认结论

用户提供的 r5 事务 `09844d9e31084c72ae4da1336717e425` 已标记 `status=failed`，约314.884秒后失败。`restarted=true` 表示失败后、没有待恢复 journal 时重新打开了原程序，不表示语音安装成功。诊断复制时的 `seconds_without_progress=332` 包括结束后的等待，不能据此判断进程仍卡在安装。

报错目标是暂存区中 `modelscope/models/cv/abnormal_object_detection/mmdet_ms/roi_head/roi_extractors/single_level_roi_extractor.py`。按用户根目录计算，最终路径204字符，事务暂存路径267字符。原代码使用普通Windows路径，依赖系统开启长路径行为；EXE内的longPathAware=true本身不够。微软文档：[Maximum Path Length Limitation](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation)。

已在真实Windows隔离进程中关闭该测试进程的longPathAware声明，使用相同长度根目录和同一相对文件名，原源码在 `output.open('xb')` 处复现同样的 `FileNotFoundError: [Errno 2]`。原始归档内容存在，出错的是创建暂存文件；不能把这个异常理解成下载漏了这个Python文件。既有语音基线清单40327文件中，有59个在用户根目录下形成至少260字符的暂存路径。清单顺序不代表归档安装顺序，不据此推算精确失败文件序号。

保留的冻结r5更新器中 `app.updates.install` 代码对象与已发布源码提交1744e5cd一致。在同样未启用长路径的隔离环境，真实r5冻结更新器也复现同一267字符文件报错，成功恢复先前已替换的夹具文件，并显示failed/restart/restarted=true。没有访问报错用户的电脑，尚未核实其实际LongPathsEnabled设置，也没有冒称该用户安装已成功。没有证据指向GPU或杀毒软件。

## 修复范围

- `app/updates/manifest.py`：增加统一的Windows Unicode扩展路径转换；先规范绝对路径，支持盘符/UNC且重复调用不叠加前缀。不改变签名相对路径、下载来源、续传或校验规则。
- `app/updates/install.py`：在安装、旧文件备份、恢复、卸载和空间计算中使用扩展路径。保持原有路径/目录联接限制、归档与文件哈希、同步写盘、原子替换及恢复计划。返回的事务路径保持调用方原有表示。
- `app/updates/cleanup.py`：统一比较归档、事务和清理路径，避免扩展/普通路径表示不同导致缓存不能识别；真实深层材料可正常清理。仍只清理已提交且明确归属本任务的材料。
- `scripts/update_entry.py`：失败后重新打开原程序时，不再把失败阶段、当前文件和计数改成restart空值。成功安装仍显示重启阶段，失败恢复后仍可自动重开原程序。
- `tests/test_long_install_paths.py`：增加真实Windows传统路径限制下的安装、修复、失败回滚、清理、卸载回归；增加失败重启诊断保留用例。
- `tests/test_inline_extraction.py`：阶段文件是否被重复哈希的原有断言改为直接检查路径分段，兼容扩展路径表示；仍拒绝任何stage文件重读校验。

## 实际验证

- 新增两例先失败：267字符暂存文件创建失败；失败重启把install覆盖成restart。修复后通过。
- 52项相关关键测试 **20.943秒通过**。覆盖安装签名/内容保护、内联哈希、锁、回滚、清理边界、用户修改备份、目录联接拒绝、旧事务恢复、训练组件兼容和真实Qt进度响应。不重复全量回归，不重新下载大型语音包。
- 最终冻结主程序/更新器 **96个应用代码对象** 与源码一致，生产公钥保持；主程序实际 `--core-check` 返回ok=true，无语音资源仍可通过核心检查。
- 真实冻结对比使用小型签名夹具和仅QA信任公钥，测试副本longPathAware=false，不修改系统注册表。r5失败后，新冻结更新器复用**同一个根目录、同一份保留缓存**重试成功，真实Qt窗口自动结束、有效文件正确、成功任务缓存/暂存/普通备份清理完成，并自动执行重启探针。
- 个人文件和r5失败时留下的无提交标记备份保持。新成功任务不会凭猜测删除旧失败事务备份。未对真实完整语音包重装、未对报错用户电脑复测；重启探针用于核对启动命令，正常产品入口另行完成核心检查。
- 测试夹具过程中修正了公钥位于onedir外置目录、测试脚本签名限制、UTF-8读取和旧失败备份应保留等夹具问题，未因此放宽产品安全或清理规则。测试子进程都已正常退出；曾过早关闭的失败QA窗口等待其读取终态后正常关闭，没有强杀安装。

证据及小型修改前快照：`work/long-install-paths-20261026/`，含red.txt、critical-tests.txt、inventory-path-analysis.json、frozen-old-failure.json、frozen-new-success.json、frozen-results.json、core-check.json、build.log及delivery.json。隔离目录不含整套语音环境副本。

## 交付及使用

`D:\TachiTalk\distribution\TachiTalk-v2.0.0-setup-r7.zip`

- 116,267,943字节，约110.88MiB；版本仍为2.0.0正式版。
- SHA256：`d888db26f8653b43c254506d0652c8289c29fa0d909895023d3ad56065a30eec`，配套.zip.sha256。
- ZIP CRC检查通过，包含EXE、配套BIN及r7说明。保留r6完整训练工作台；可选语音/训练资源不进入主程序安装器。

r5用户关闭旧程序和已结束的失败窗口，完整解压ZIP，保持EXE/BIN同目录；运行安装器并选择**原TachiTalk安装目录**覆盖主程序。不要删除下载缓存或事务备份。启动后如有未完成事务先等待恢复，再进入更新与语音资源安装/修复。隔离夹具已证实原有效缓存能被复用；真实用户的缓存可用性仍由原签名与哈希检查决定。

未覆盖桌面日常安装，未升级GPT-SoVITS/PyTorch/CUDA，未读生产私钥、未签新资源清单，r6训练上传三文件不变。本轮未提交/推送/发布GitHub，也未改魔搭云端；HEAD4666ea0及原未提交修改保留。

开发回滚可使用before中本轮业务文件小型快照；用户需要回滚主程序可同目录安装原r6/r5，保留user_data及语音资源，但旧版会重新存在此路径限制问题。
