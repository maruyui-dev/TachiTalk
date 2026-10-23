# 模块化安装与更新实施状态

更新时间：2026-10-23。目标版本：**v1.3.0**。

## 2026-10-23 上传GitHub、桌面安装包与最终清理（用户已授权，进行中）

- 最新授权：上传正式1.3.0到GitHub；桌面留一份主程序安装包；保留Python项目和原本本地GPT-SoVITS，清理代理生成的TachiTalk副本/构建产物；删除失败必须提供具体到文件名的完整路径清单。
- 已只读核实GitHub现有凭据有效且对 `maruyui-dev/TachiTalk` 有push权限；没有打印/保存Token。正式v1.3.0不存在，当前只有v0.2.0。创建新版草稿并上传，旧发布/稳定标签不覆盖。
- 桌面真实路径 `D:/桌面`，已复制 `TachiTalk-v1.3.0-main.zip` 并核对原SHA。随后发现README仍有0.2旧便携启动步骤，已修正文档，并只重新编译受影响的main/full安装器（不重压/重签语音）；完成后须更新桌面ZIP和附件哈希。
- 全量发布回归exec20121，日志 `work/full-tests-before-github-publish-20261023.txt`。README安装器重新编译exec49614，日志 `work/production-main-readme-rebuild.log` 与 `work/production-offline-readme-rebuild.log`。
- 公开源历史与本地完整历史没有共同祖先，差异仅为公开历史剔除的119MB超分ZIP/训练清单。不得把本地完整历史强推远端。使用基于公开main的隔离checkout，只复制本次源码改动，提交到新的公开分支，再将1.3.0 release指向该提交；不改原工作分支/HEAD/稳定标签。
- 已启动 `work/github-release-transfer.py --phase upload --voice-only`，exec56587，日志 `work/github-voice-upload.log`；持久化远端草稿ID与逐附件状态在 `docs/release-evidence-1.3.0/github-upload-state.json`。该文件不含凭据，只含公开附件ID/hash。上传API按SHA验证，未验证完不得删本地正式附件。
- 上传完成/公开校验前不执行最终清理。清理前把main/voice基线inventory和必要测试证据归入Python项目，保留生产密钥、原始services/独立GPT、用户配置与.git/.venv。dist/build/scratch/work、旧桌面包/备份等派生产物按明确目标检查后删除；未知归属/被拒路径写逐文件CSV清单，不把失败写成成功。
- 下一步：等正式安装器重编译完成→更新ZIP/桌面副本/附件账目→分组上传并验证→公开源提交与发布→下载/签名/Range线上实检→完成清理与详细失败清单。任何中断先查实际进程和本节账目，不盲重传或删尚未上传文件。

## 2026-10-23 用户授权清理及正式发布准备（本地交付已备齐；新增暂存删除被工具拒绝）

- 用户明确授权：不影响后续GitHub上传则清理两套大QA副本，并继续后续任务。不删除dist/build等本轮前既有资源，不推送/发布远程。
- 最新4个语音分卷逐个SHA及合并SHA/长度验证通过，原QA清单验签通过；`work/retained-voice-verification.txt`。保留原压缩字节可复用正式签名，无需重压语音。
- 执行脚本 `work/cleanup-authorized-20261023.ps1`：先核对两个根及全部子项没有reparse逃逸、无测试进程、所有删除绝对路径在授权根内。将4个分卷同盘Move到 `work/production-release-1.3.0/voice`，复制unsigned-payload/inventory；QA根的JSON/截图/trust/清单原位保留。仅原生PowerShell逐项Remove-Item，未访问生产私钥。
- 清理进程exec会话98052（实际状态需查进程/日志），进度 `work/cleanup-20261023/result.json`、`work/cleanup-authorized-20261023.log`。若中断先读plan的completed/errors和实际文件，不能重新盲跑脚本（要求全新目标防覆盖）。
- 正式公钥的主程序/独立updater已开始重新冻结：exec会话49984；日志 `work/production-main-build.log`；输出 `work/production-release-1.3.0/TachiTalk`，构建/安装器 `build-main`。这一步不覆盖已有dist或稳定安装。
- 下一步：核对清理回收空间与构建结果；在隔离QA目录验证正式公钥客户端核心UI，准备正式voice未签名清单与主程序基线inventory、完整离线安装器及发布文件列表。生产签名需维护者自行在本地隐藏输入密码，不索取密码、不代读私钥。
- 主程序/独立updater冻结和正式main-only安装器编译已退出0。`work/production_release_smoke.py` 对同一冻结客户端编译隔离QAMode安装器并测试，`production-release-1.3.0/final-smoke.json` 确认核心UI/正常启动关闭、正式公钥内置、updater拒绝qa-only签名全部通过，exec93893退出0；安装未写稳定注册项/快捷方式。
- 首次正式 `main-1.3.0-inventory.json` 已生成；为未来1.3.0→后续版本文件差异保留基线。不虚构1.3.0到同版本的更新包。
- 完整离线安装器正在从原始推理源构建一次，exec10122，日志 `work/production-offline-build.log`，暂存 `production-release-1.3.0/build-offline/voice-stage`；编译后需安全移除本次暂存，避免再次留下9GB重复副本。旧dist/build不动。
- 正式voice未签名清单已补标题/说明，与已校验分卷保持相同archive/parts哈希；已准备 `work/production-release-1.3.0/sign-voice.ps1`，通过异步问题请维护者在自己的PowerShell运行以隐藏输入私钥密码。代理仅执行过签名工具--help，未执行该签名脚本/未读生产私钥；继续等待用户签名结果。
- 清理exec98052已退出0，计划30项全部完成、errors为空。`cleanup-20261023/result.json` 记录磁盘净增加96,336,707,584字节（89.72 GiB）；同期正式构建产生了新文件，因此不是删除文件逻辑大小的简单相减。两个QA根的小JSON/清单/截图保留，4个正式复用分卷在新目录。
- 用户运行ps1被系统执行策略阻止，未降低策略。改为用户在PowerShell直接设置仅私钥路径环境变量并运行独立Python签名工具，隐藏输入密码；用户已完成。
- **正式生产签名验证通过**：代理只读取公开的voice-manifest，使用客户端 `release-1` 公钥验签，payload与准备的unsigned清单一致，40,327文件/4分卷；`production-signature-verification.json`。生产私钥/公钥匹配得到实际签名证据，代理未读私钥或密码。
- **原生正式updater验证通过**：读取冻结包内公钥与源码一致；隔离测试根使用上述正式清单+故意损坏的微小archive，实际updater接受正式签名后在包完整性处拒绝，未创建services或pending。`native-production-signature-verification.json`、`work/native-production-signature-verification.log`；没有重复解压/安装9GB语音。
- 完整离线正式编译已退出0，ISCC压缩309.641秒，`work/production-offline-build.log`；本次未再安装该正式完整包，不将之前QA完整安装/实际推理冒充其再次验收。
- `work/prepare-production-upload.py` 实际退出0：最终12个公开附件位于 **`work/production-release-1.3.0/upload`**；SHA256SUMS与 `upload-assets.json` 已生成，清单与分卷哈希一致。主程序ZIP内容/CRC检查通过，77,936,741字节；完整离线exe+3bin共4,647,572,386字节；语音4分卷6,219,221,474字节。附件总大小（不含小型校验表）10,952,318,244字节（约10.20 GiB）。最终附件不含私钥、用户配置、QA信任根或工作目录。
- 正式附件完成后，尝试清理本轮新增 `D:/TachiTalk/work/production-release-1.3.0/build-offline/voice-stage`（约9.4 GiB）**被工具自动审批拒绝**。返回仅 `blocked by policy`，未给具体原因；再次用单独明确绝对路径Remove-Item也被拒，未执行删除，不更换底层方式绕过。单独只读预检确认路径在本次工作区内、无reparse、upload及正式签名验证就绪，`cleanup-20261023/production-staging-preflight.json`。该暂存不在upload内，可由用户在资源管理器手动删除，不影响附件。
- 最终D盘可用177,736,019,968字节（165.53 GiB），较本次清理前92,287,049,728字节净增85,448,970,240字节（79.58 GiB）。这已计入正式包和仍保留的新暂存占用。不要以清理过程89.72 GiB净增数字代替最终净增。
- 公开交接说明 **`docs/release-1.3.0.md`** 已创建。main基线inventory和客户端保留；小型证据原位保留，语音分卷最终已从voice目录移入upload（不再生成重复副本）。签名清单在voice和upload各保留一份小JSON。
- 最后Git空白检查通过、稳定标签两个OID未变；未提交、推送、上传或创建Release。下一步审核upload附件清单；用户明确授权上传后才操作GitHub。线上GitHub/代理、Win10/RTX50、正式完整离线包再次安装等仍未验证；无需重跑已通过的大包压缩。

## 2026-10-23 D盘占用核查（已盘点，尚未删除）

- 用户发现D盘空间减少约200G，要求解释。已只读统计项目文件大小，跳过reparse/junction，不读取用户/签名私钥内容，不删除文件、不更改环境。
- `work/disk-usage-audit-20261023.json`：项目文件逻辑总大小208.572 GiB；统计无权限错误，跳过5个reparse点。D盘当时可用92,287,619,072字节（约85.95 GiB）。逻辑大小不是精确物理占用，回收量须以清理前后磁盘空闲实测。
- 本任务明确创建的 `work/release-qa-130-v2` 63.507 GiB、`work/release-qa-130-final` 35.746 GiB，合计99.253 GiB，包含本地语音资源重复复制、ZIP/分卷、解压暂存、离线测试安装及事务备份。本任务结束前未收尾清理，这是本任务空间增长的重要原因。
- 其他当前目录：dist46.335 GiB、build31.440 GiB、scratch10.034 GiB、_qt_runtime_tmp7.960 GiB、原始services9.832 GiB。详细账目 `work/disk-usage-detail-20261023.json`。dist/build/scratch有本轮模块化任务之前（10月21日、10月22日18点前）已存在的安装包/CUDA缓存/旧runtime备份，不能全部归为本轮新增或直接删除。
- 尚未对全D盘做递归扫描，不能认定用户损失的全部200G都是本任务新增。两个大QA目录已明确可作为清理候选；需保留原始services、配置/角色资源、源码/.git、生产密钥、进度与测试证据。不要整目录清空work或build。
- 当前没有发现TachiTalk/独立更新器/ISCC命名的QA进程；未删除任何目录。下一步向用户说明具体账目，得到清理范围授权后，先保留小型JSON/日志/清单等证据，验证所有删除绝对路径在指定测试根内且无reparse逃逸，再使用原生PowerShell逐项清理并实测回收量。不能跨shell拼接删除，不得动稳定标签。

## 2026-10-23 生产公钥接入（已完成配置）

- 维护者确认已自行生成密钥。只读取 `D:/TachiTalkSigning/release-1/release_keys.json`，校验Base64及32字节Ed25519公钥后，合并到 `packaging/release_keys.json`；key-id `release-1`，无旧键冲突。未读取/复制私钥或索取密码。
- 公钥原始字节SHA-256：`de76beada1bca8d0316b4737b605a8cb94bda835e30fd5cfa5b65652594c34ed`。实际接入日志 `work/production-public-key-import.txt`，退出0；源与目标公钥一致。
- `.venv/Scripts/python.exe -X utf8 -B -m unittest tests.test_updates.ManifestTests tests.test_component_release -v`：**5项通过，1.693秒，退出0**，`work/production-public-key-regression.txt`。仅配置/文档变更，未新增测试实现，未重新全量回归或冻结安装包。
- 构建器会将该配置分别打包到主程序和独立更新器；接入时需要重新冻结，现已在顶部正式发布准备阶段完成。既有QA产物仍不可发布。
- 本段当时未进行生产签名；最新进展见顶部：维护者已本机签发，生产验签和正式构建已完成。私钥/密码仍由维护者安全备份，无需再次生成或替换公钥。
- 工作分支/HEAD/稳定标签与下方快照一致；公钥可提交，私钥仍在仓库外。不自动提交、推送或发布。建议本次配置接入建立开发检查点。

## 2026-10-23 密钥目录权限报错跟进（工具修复通过；独立Python与外部目录预检通过）

- 用户实际运行生成命令，输入密码后在创建 `%LOCALAPPDATA%\TachiTalkSigning` 时遇到 WinError 5；该次在写入密钥前失败。
- 已重新检查工作区、HEAD和稳定标签，均与下方记录一致；保留全部修改。
- PowerShell/.NET 的无密钥临时目录探测可写，但同一执行环境的 Python mkdir（0777、0700均测）被拒绝；Python token 的 IsTokenRestricted=False。尚未确定具体系统/终端拦截来源，未修改ACL、未提权，不能宣布权限已解除。
- 已添加行为回归并实际RED：8项中2项失败，证实目录错误发生在询问密码之后且异常未转为可操作提示、缺少无密码预检。日志 `work/signing-directory-red.txt`。
- `scripts/create_signing_key.py` 已提前实际写入预检，增加 `--check-directory`、明确错误提示、取消/密码不匹配的空目录清理；保留已有/部分写入密钥，不覆盖。`tests/test_signing_setup.py` 增加对应回归，并实际证明含 `@` 且足够长的测试密码可加密/解密，只有 `@@@` 会因长度不足而拒绝。
- 本次命令 `.venv/Scripts/python.exe -X utf8 -B -m unittest tests.test_signing_setup tests.test_component_release tests.test_updates.ManifestTests -v`：**17项通过，1.270秒，退出0**；`work/signing-directory-green.txt`。未重跑此前340项全回归，未改客户端/推理环境，不重建既有大包。
- 原目录实际预检：`.venv/Scripts/python.exe -X utf8 -B scripts/create_signing_key.py --directory "$env:LOCALAPPDATA\TachiTalkSigning\release-1" --check-directory`，**退出2，仍为WinError5**；已无Traceback、未询问密码、无目标目录/密钥文件，见 `work/signing-directory-localappdata-check.txt`。如实记录为未通过权限验收。
- `docs/modular-updates.md`、`docs/modular-updates-validation.md` 已补充预检操作和真实限制；Git差异空白检查通过。未提交，建议本次工具修复可建开发检查点，不能标为生产密钥就绪。
- 用户再次确认PowerShell中仍失败。本轮进一步真实对比：项目 `.venv/Scripts/python.exe` 的标准库mkdir与直接CreateDirectoryW均WinError5，系统现有 `D:/Python/python.exe`（3.14.6，cryptography50.0.2）及uv基础解释器创建同区域无密钥目录成功；没有安装/升级任何依赖。具体导致虚拟环境进程受限的系统策略尚未确定。
- AppData目标父目录的 `.resolve()` 在两解释器中均可显示Codex包 `LocalCache/Local` 路径，故推荐改用仓库外独立 `D:/TachiTalkSigning/release-1`，避免把长期发布密钥保存在应用缓存路径。未改ACL、未关闭防护、未提权。
- **真实可用命令**：`D:/Python/python.exe -X utf8 -B scripts/create_signing_key.py --directory D:/TachiTalkSigning/release-1 --check-directory`，退出0、显示目录可写、退出后目标子目录不存在；`work/signing-system-python-external-check.txt`。独立Python原AppData路径预检也退出0：`work/signing-system-python-check.txt`；项目虚拟环境对照仍退出2：`work/signing-venv-recheck.txt`。
- 当时下一步为维护者隐藏输入密码生成；现已确认生成并接入公钥，见上方最新记录。这里的权限诊断证据保留，不重复执行密钥生成。

## 当前结论

**本地实现和验收已完成；正式发布前提尚未满足，不能称为已发布或全平台验收完成。**

- 密钥工具本次修复前的主功能全量回归：**340项通过，366.764秒**，进程退出0；`work/full-tests-verified-release-20261023.txt`。本次工具修复单独17项回归见上方。
- 生产公钥最新冻结/隔离主程序安装、无语音核心自检及正常启动关闭全部通过；`work/production-release-1.3.0/final-smoke.json`。此前QA构建证据仍保留。
- 独立语音 ZIP 的原生安装→实际 GPU 推理→托管卸载→卸载后核心 UI 全链通过；`work/release-qa-130-v2/resumed-results.json` 最后一项 `resumed_qa_finished.ok=true`。
- 两套大QA根的stage/备份/安装副本已按授权清理，证据保留；正式包新增暂存被工具拒绝删除，详见顶部。没有待恢复journal或遗留本任务安装器/推理进程。
- **生产公钥 `packaging/release_keys.json` 已接入 `release-1`**，最新正式主程序与更新器已重新冻结，正式voice清单通过验签。既有QA构建不可分发。私钥和密码不进入仓库/聊天/客户端。
- 没有提交、推送、发布Release、覆盖远程资产或修改稳定标签。建议现在建立本地开发检查点，但不能标记为稳定发布。

## Git 与稳定基线

- 实际项目：`D:\TachiTalk`，不是Codex项目外壳目录。
- 当前分支：`feature/modular-updates`。
- HEAD：`4666ea0e1b3f255e4ee6276294e7582781f42414`，开始时main工作区干净；所有当前修改均属于本任务，尚未提交。
- 稳定标签对象：`979a8fba7a18acaae7c579ed7795ddf75a08d9de`；解引用：`8eb0d2b145ea065ba23f8035abb94ac0c9036956`，与开始时一致。
- 当前HEAD比指定稳定基线新，保留了已有发布回归与文档提交，没有退回基线或丢弃用户数据。
- `git -c core.whitespace=cr-at-eol diff --check` 通过；保持基线CRLF，不改换行策略。
- 私有Python3.9.13 / torch2.7.1+cu128 / CUDA12.8 / GPT-SoVITS推理版本未升级、未替换。

## 阶段与完成条件

| 阶段 | 条件与实际结果 |
| --- | --- |
| A 检查与边界 | 已读README、入口、配置、UI、服务启动与PyInstaller/Inno/便携流程；稳定标签和工作区已核对 |
| B 可选语音 | 无语音安装版的真实正常启动/关闭、核心UI、资源状态、文字/字幕/立绘及回退测试通过 |
| C 资源与下载 | 后台UI、三组独立源、待命代理、离线导入、Range/ETag/断流/切源/坏包拒绝及200坏清单回退通过 |
| D 更新 | 启动后后台检查、版本说明弹窗、稍后继续、精确基线/组件版本和文件差异ZIP通过 |
| E 安全与可靠性 | 内置公钥验签、整包/文件SHA、独立helper等待/重启、安装锁、备份计划、崩溃恢复、占用回滚、托管卸载和旧目录复用通过 |
| F 本地交付验收 | 340项主功能回归及后补专项通过；正式公钥构建/核心UI、正式voice签名/原生updater坏包拒绝、完整离线编译和附件汇总通过。真实Release/公共代理及其他硬件验收未做 |

各主功能本地阶段已有实际证据，可建议开发检查点；未创建阶段性提交。后补密钥工具修复、独立Python预检、生产公钥、正式语音签名和本地正式构建已完成；远端发布/线上验证未完成，详见顶部跟进。

## 已完成实现与文件

完整逐文件作用表在 `docs/modular-updates-validation.md`，操作/构建命令在 `docs/modular-updates.md`。

- `app/version.py`：1.3.0；`app/core/components.py`、`app/ui/desktop.py`：缺语音或坏配置时文字回退、延迟检查。
- `app/paths.py`、`scripts/start_tts.py`：复用用户手选旧语音目录与参考音频，不移动环境，不改稳定推理逻辑。
- `app/updates/{manifest,download,client,install}.py`：规范JSON/Ed25519、来源约束、断点/哈希/回退、清单缓存、独立组件与文件事务。
- `app/ui/update_controls.py`、`app/ui/control_panel.py`、`resources/control_panel/character_control.ui`：资源入口、后台任务、进度/暂停/重试/导入、更新说明及迁移入口。
- `app/bootstrap.py`、`scripts/update_entry.py`：独立恢复、父进程退出后替换、失败恢复/重启；等待超时不启动重复主程序，交接前暂停阻止安装。
- `main.py`、`app/release_check.py`：保留真实推理自检，增加核心UI离线验收；另以正常启动入口实测无语音状态。
- `packaging/download_sources.json`：附件/API/清单分组配置；官方正常时不使用代理，普通源失败后自动尝试待命代理，显式禁用不重开。
- `packaging/release_keys.json`：生产信任根占位，当前空库安全拒绝远程安装。
- `scripts/build_release.py`、`packaging/TachiTalk.spec`、`packaging/TachiTalk.iss`：复用onedir/Inno，独立updater、可选语音、用户权限、QA模式、许可证与说明。
- `scripts/component_release.py`、`scripts/sign_manifest.py`、`scripts/create_signing_key.py`、`scripts/package_portable.py`：推理筛选、文件差异ZIP、分卷、分离签名、加密密钥生成、兼容新旧客户端的便携包去重。
- `requirements.txt`：客户端增加cryptography47.0.0；`.gitignore`：隔离QA/事务产物。
- `tests/test_optional_voice.py`、`test_updates.py`、`test_update_ui.py`、`test_update_entry.py`、`test_component_release.py`、`test_signing_setup.py`：对应行为和故障回归。
- `tests/test_desktop.py`：证明基线在重I/O下也有提前关闭计时问题后，调整看门狗启动点，保留功能断言与总超时；`test_portable_package.py`：重复条目回归。
- `tests/run_modular_release_qa.py`、`resume_modular_release_qa.py`、`run_restart_qa.py`、`run_legacy_migration_qa.py`：隔离Windows原生发布验收驱动。
- `README.md`、`packaging/安装说明.txt`、两份模块化文档和本状态文件：流程、测试/失败证据、风险与恢复。

## 关键真实证据

| 命令/项目 | 结果与日志 |
| --- | --- |
| `.venv/Scripts/python.exe -X faulthandler -X utf8 -B -m unittest discover -s tests -v` | 最终340通过366.764s；`work/full-tests-verified-release-20261023.txt`。之前332/337/338通过分别属于较早快照，不混同 |
| 最新源码冻结 | `scripts/build_release.py --output work/verified-release-build/TachiTalk --work-dir work/verified-release-build/freeze --trust-keys work/release-qa-130-v2/trust/release_keys.json`；退出0，`work/verified-release-build.log` |
| 最新主程序QA安装 | `work/verified_release_smoke.py`：真实Inno QAMode编译、中文/空格路径安装、README/LICENSE/NOTICE哈希、核心UI、正常入口启动关闭通过；`work/verified-release-smoke.log` / `final-smoke.json` |
| 当前QA主程序文件 | `work/verified-release-build/main-setup`：setup2,153,936字节、bin75,790,206字节；仅QA，不分发 |
| 完整离线Inno与真实推理 | `work/release-qa-130-v2/results.json` / `tts-full.json`，完整安装后的筛选环境已实际合成非静音PCM |
| 独立语音安装与推理 | 40,327文件，原始10,037,222,548字节；ZIP6,219,221,474字节/4分卷；原生安装1373.62s，推理47.6s，70,400字节非静音32kHz PCM，RTX4060 Laptop/原torch与CUDA；`tts-downloaded.json` |
| 原生卸载与卸载后核心 | 1173.2s，未登记legacy文件保留，核心UI/字幕/立绘/资源面板可用，语音未安装检测正确；`voice-uninstall-result.json` / `core-after-voice-uninstall.json` / `resumed-results.json` |
| 上次中断恢复 | 本次确实发现pending并经独立helper恢复成功204.26s；`work/release-qa-130-v2/recovery-result.json` |
| 占用/失败回滚与等待父进程 | 原生Win32占用实际失败后恢复旧EXE并可核心启动；`work/release-qa-130-v2/results.json` |
| 原生重启、旧目录免复制 | `work/restart-reviewed-qa/result.json` / `work/legacy-reuse-qa/result.json`，后者含真实GPU推理 |
| 后补安全/打包边界 | 生命周期11项、密钥/签名10项、便携8项、清单/下载/UI36项专项通过；最终340项已纳入所有新回归 |

原生语音QA使用的helper有完整批量事务修复；最后客户端的清单回退修复未改变该安装事务或推理链。所有测试安装根均在 `work/`，没有对稳定安装做破坏性测试。

## 已修复问题与历史失败

- 原QDialog.finished重名、测试延迟销毁和Windows8.3路径断言问题已复现修复。
- 早期321项曾1失败+1错误；只读加载4666ea0也复现桌面计时问题，修复后后续全回归通过，未隐瞒失败。
- 四万文件每次重写全journal的平方级I/O已真实RED后改为先备份全部文件、一次持久化计划，再替换；仍有较高文件级I/O耗时。
- 等待父进程失败仍重启、交接暂停仍启动helper、便携ZIP重复文档、HTTP200坏清单不继续切源均有真实RED与修复后回归。
- 密钥测试曾因外部目录WinError5及tempfile重试卡住，已停止仅该测试进程并改受控夹具；生产路径保护不放宽，未生成生产私钥。原诊断和历史日志保留。
- 初次PowerShell串联GUI安装器未等待其结束；核对实际安装日志后改用Python subprocess.run等待，原失败不计为通过。

## 剩余发布前提与风险

1. 正式语音清单已由维护者签发并通过公钥验签；维护者仍需将私钥和密码分别安全备份，不发聊天。
2. 正式公钥客户端/更新器与完整离线安装器已构建，upload附件备齐；QA公钥产物不能改名充当正式包。每个后续latest发布目录要附受支持main基线清单与当前voice清单。新增暂存目录需用户手动清理（工具拒绝），不影响上传。
3. 未测试真实GitHub大文件、公共代理的速度/Range/可用性及生产签名Release。已用本地HTTP实现故障注入和安全降级，不能冒充线上通过。
4. Windows10、RTX50、干净系统、杀毒/权限环境、真实断电/磁盘损坏、Inno强制中断未做目标实机验收。
5. 安装约23分钟、卸载约19.6分钟；文件级I/O慢、stage/备份保留占空间，无自动清理策略。当前没有“新版启动健康检查失败后自动回滚”协议，不能把文件事务成功当作新版所有硬件健康保证。
6. 完整离线Inno及独立ZIP实测；新便携筛选/去重工具通过回归，本轮未重压全量便携ZIP。模型/第三方依赖再分发权利仍按原许可证维护。

## 下次如何继续

- 先读本文件及两份文档，再检查Git分支/status/diff/log、稳定标签、实际代码和进程/journal；以实际证据为准。
- 若只需继续发布：正式构建与签名已完成，审核 `production-release-1.3.0/upload-assets.json` 和upload目录；获得明确上传授权后操作GitHub，发布前核对标签/资产冲突。不要再次生成密钥或重压无变化的大包。新增9.4GiB暂存的工具删除被拒，若用户手动清理后应核对空间。
- 若源码有新修改，只跑相应验证及必要构建；没有新变化时不重复全部测试。
- 保留用户数据和稳定标签，禁止reset --hard/clean -fd/强推。没有新的明确发布指令时不推送、不发布或覆盖远端资源。

## 当前Git工作区

下方快照由最终核对生成；修改均未暂存/提交。完整差异以实际Git为准。

```text
## feature/modular-updates
 M .gitignore
 M README.md
 M app/bootstrap.py
 M app/paths.py
 M app/release_check.py
 M app/ui/control_panel.py
 M app/ui/desktop.py
 M main.py
 M packaging/TachiTalk.iss
 M packaging/TachiTalk.spec
 M packaging/安装说明.txt
 M requirements.txt
 M resources/control_panel/character_control.ui
 M scripts/build_release.py
 M scripts/package_portable.py
 M scripts/start_tts.py
 M tests/test_desktop.py
 M tests/test_portable_package.py
?? IMPLEMENTATION_STATUS.md
?? app/core/components.py
?? app/ui/update_controls.py
?? app/updates/
?? app/version.py
?? docs/modular-updates-validation.md
?? docs/modular-updates.md
?? packaging/download_sources.json
?? packaging/release_keys.json
?? scripts/component_release.py
?? scripts/create_signing_key.py
?? scripts/sign_manifest.py
?? scripts/update_entry.py
?? tests/resume_modular_release_qa.py
?? tests/run_legacy_migration_qa.py
?? tests/run_modular_release_qa.py
?? tests/run_restart_qa.py
?? tests/test_component_release.py
?? tests/test_optional_voice.py
?? tests/test_signing_setup.py
?? tests/test_update_entry.py
?? tests/test_update_ui.py
?? tests/test_updates.py
```
