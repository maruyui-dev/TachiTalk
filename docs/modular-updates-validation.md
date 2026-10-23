# v1.3.0 实施与验收记录

本记录配合 `IMPLEMENTATION_STATUS.md` 和 `docs/modular-updates.md` 使用。实际日志在项目忽略的 `work/`，不将未执行的线上验收标成通过。2026-10-23 主功能源码 **340项全量回归通过（366.764s）**；无语音正常启动关闭、独立语音 ZIP 原生安装、真实推理、托管卸载及卸载后核心UI全链通过。之后密钥工具修复17项、公钥接入5项回归通过；再后正式公钥冻结/核心UI、正式语音验签、原生updater验签/坏包拒绝及完整离线编译通过。没有重新执行全量回归或正式完整包的再次安装。真实Release/公共代理线上验收未完成，旧QA二进制不可发布。

### 最新：正式产物与授权清理（2026-10-23）

| 实际操作 | 结果与证据 |
| --- | --- |
| 最新语音4分卷复用前校验 | 各卷SHA、合并SHA/大小及原QA签名通过，`work/retained-voice-verification.txt`；不重复压缩 |
| 用户授权的两套大QA清理 | 原生PowerShell检查绝对路径/全部子项无reparse后逐项删除，30项完成、0错误，`work/cleanup-20261023/result.json`；保留JSON/截图/清单并同盘移动最新分卷 |
| 正式公钥主程序及updater冻结/主程序安装器 | `scripts/build_release.py --main-only --compiler <原ISCC> --output work/production-release-1.3.0/TachiTalk --work-dir work/production-release-1.3.0/build-main` 退出0，`work/production-main-build.log` |
| 同冻结客户端隔离安装/正常启动关闭 | `python -m work.production_release_smoke` 退出0；QAMode不改稳定注册/快捷方式，核心UI、缺语音回退、正式公钥读取、旧QA签名拒绝通过；`production-release-1.3.0/final-smoke.json` |
| 用户本机签发正式语音清单 | ps1被执行策略阻止后用直接Python命令成功；未降低策略。`release-1`公钥验证40,327文件/4分卷清单及prepared payload一致，`production-signature-verification.json`；代理未读生产私钥/密码 |
| 正式原生updater信任根与坏包拒绝 | 内嵌公钥与源码一致；隔离根中正式清单通过签名后拒绝微小损坏archive，未建services/pending；`native-production-signature-verification.json` |
| 正式完整离线构建 | `build_release.py --skip-freeze ... --work-dir work/production-release-1.3.0/build-offline` 退出0，ISCC压缩309.641秒；`work/production-offline-build.log`；本次未再安装完整包 |
| 附件汇总/哈希/主程序ZIP检查 | `python -m work.prepare-production-upload` 退出0，12项共约10.20GiB，SHA表和清单分卷一致；主程序ZIP文件集合与CRC通过。`upload-assets.json`、`work/prepare-production-upload.log` |

最终D盘可用165.53GiB，较本次清理前净增79.58GiB，已计入正式包及尚存的新9.4GiB构建暂存。该暂存删除两次被工具自动审批拒绝，仅返回 `blocked by policy`，未说明具体原因；未删除、未绕过。目标 `production-release-1.3.0/build-offline/voice-stage` 不在upload，可由用户在资源管理器手动删除。旧dist/build、原始语音、用户数据及生产密钥未清理。发布交接见 `docs/release-1.3.0.md`；未提交/推送/上传/发布。

### 后补：生产公钥接入（2026-10-23）

维护者确认生成后，仅导入 `D:/TachiTalkSigning/release-1/release_keys.json`，验证Base64/32字节Ed25519和键ID无冲突，合并到 `packaging/release_keys.json`。公钥原始字节SHA-256 `de76beada1bca8d0316b4737b605a8cb94bda835e30fd5cfa5b65652594c34ed`；源与目标配置一致，`work/production-public-key-import.txt`，退出0。未读取私钥，未索取密码，未生产签名。

命令 `.venv/Scripts/python.exe -X utf8 -B -m unittest tests.test_updates.ManifestTests tests.test_component_release -v`：**5项通过，1.693秒，退出0**，`work/production-public-key-regression.txt`。这证明公钥配置格式和既有签名/差异包逻辑回归，不证明生产私钥/公钥匹配或正式发布验收。既有QA二进制未重新构建，仍不可发布。

### 后补：密钥目录 WinError 5（2026-10-23）

- 用户在两次隐藏输入后遇到目录创建 WinError 5；当次未写出密钥。已增加实际写入预检且早于密码提示，`--check-directory` 可无密码运行；只清理本次新建的空目标目录，已有文件与部分写入密钥保留，错误返回2并给出操作建议。
- RED：`tests.test_signing_setup` 共8项中2项失败，复现未处理权限错误/缺少预检，见 `work/signing-directory-red.txt`。GREEN：`.venv/Scripts/python.exe -X utf8 -B -m unittest tests.test_signing_setup tests.test_component_release tests.test_updates.ManifestTests -v` 共 **17项通过，1.270秒，退出0**，`work/signing-directory-green.txt`；含目录/文件拒写、取消、密码不匹配、部分密钥保护及 `@` 密码加密/解密。
- 真实原路径预检仍 **退出2，WinError5**，`work/signing-directory-localappdata-check.txt`；无密码提示、无Traceback、目标目录未留下、未生成密钥。PowerShell/.NET可建临时目录，Python创建同区域临时目录却被拒，TokenRestricted=False；尚未查明具体终端/系统策略来源，未修改ACL、未提权。需维护者在普通独立PowerShell预检后生成，不能声称真实密钥生成通过。
- 用户继续报告失败后，已进一步隔离到项目虚拟环境进程：该进程标准库mkdir/直接CreateDirectoryW均被拒，系统现有独立 `D:/Python/python.exe`（3.14.6，cryptography50.0.2）可写，未安装或升级依赖。命令 `D:/Python/python.exe -X utf8 -B scripts/create_signing_key.py --directory D:/TachiTalkSigning/release-1 --check-directory` **退出0、目标子目录已清理**，`work/signing-system-python-external-check.txt`；原AppData路径独立Python预检也退出0，`work/signing-system-python-check.txt`；`.venv`对照仍退出2，`work/signing-venv-recheck.txt`。AppData解析曾显示Codex包LocalCache，改为独立D盘目录存放长期密钥。解释器进程差异的底层系统策略尚未确定；有真实可用预检方式，但未代替维护者生成私钥。

## 基线与保护范围

- 项目实际位于 `D:\TachiTalk`，工作分支 `feature/modular-updates`，起始 HEAD `4666ea0`。稳定标签对象 `979a8fba7a18acaae7c579ed7795ddf75a08d9de` 解引用为 `8eb0d2b145ea065ba23f8035abb94ac0c9036956`，没有移动、覆盖或删除。
- 起始工作区干净；本任务代码保留在工作区，没有推送或发布。实际 HEAD 比指定稳定基线新，包含既有发布回归和文档修改，未退回旧提交。
- 版本按用户补充设为 **1.3.0**。实际打包为 PyInstaller onedir + Inno Setup；业务代码仍在 EXE 内。小改动重发该 EXE 和实际改变的客户端依赖，不改写原有加载器。
- 私有 GPT-SoVITS Python 3.9.13 / PyTorch 2.7.1+cu128 / CUDA 12.8 保持原版本。客户端 Python 3.12 仅增加签名校验依赖 cryptography 47.0.0。
- 所有安装、占用文件和故障测试均在 `work/` 的隔离根执行，没有以稳定安装目录作为破坏性夹具。

## 修改文件与模块边界

| 文件 | 作用 |
| --- | --- |
| `app/version.py` | 主程序版本 1.3.0 |
| `app/core/components.py`、`app/ui/desktop.py` | 可选语音检测、配置恢复后文字回退、延迟后台检查 |
| `app/paths.py`、`scripts/start_tts.py` | 保持原服务布局，支持复用用户选择的旧语音目录及其参考音频 |
| `app/updates/manifest.py` | Ed25519、规范 JSON、大小/哈希、Windows 路径及组件操作边界 |
| `app/updates/download.py` | 有限重试、待命代理、独立来源策略、持久续传和进度 |
| `app/updates/client.py` | 检查/缓存签名清单、下载分卷、合并与验证 |
| `app/updates/install.py` | 安装锁、暂存校验、完整备份计划、替换/删除、崩溃恢复和托管卸载 |
| `app/ui/update_controls.py`、`app/ui/control_panel.py`、`resources/control_panel/character_control.ui` | 资源导航、后台任务、更新说明弹窗、下载设置、离线导入和旧目录选择 |
| `app/bootstrap.py`、`scripts/update_entry.py` | 启动前独立恢复、等待主程序退出、独立替换、失败恢复与重启 |
| `main.py`、`app/release_check.py` | 隔离验收入口，保留已有真实推理自检，增加不依赖语音的核心 UI 自检 |
| `packaging/download_sources.json`、`packaging/release_keys.json` | 可编辑默认源与内置发布公钥；已接入维护者生产公钥release-1 |
| `scripts/build_release.py`、`packaging/TachiTalk.spec`、`packaging/TachiTalk.iss` | 复用既有冻结/安装流程，主程序与完整包、独立 updater、最低权限、QA 模式 |
| `scripts/component_release.py`、`scripts/sign_manifest.py`、`scripts/package_portable.py` | 推理资源筛选、独立组件 ZIP、文件差异包/分卷、离线签名，保留完整便携包流程 |
| `scripts/create_signing_key.py`、`tests/test_signing_setup.py` | 本地交互生成加密私钥/公开配置，拒绝仓库内路径和覆盖；加密、签名一致性及无交互终端行为回归 |
| `requirements.txt`、`.gitignore` | 客户端签名依赖、忽略隔离 QA 产物及事务文件 |
| `tests/test_optional_voice.py`、`tests/test_updates.py`、`tests/test_update_ui.py`、`tests/test_update_entry.py`、`tests/test_component_release.py` | 文字回退、HTTP、签名、事务、UI、生命周期和差异包回归 |
| `tests/test_portable_package.py` | 新旧客户端进入完整便携包时，说明/许可证及语音文件只能出现一次的回归 |
| `tests/test_desktop.py` | 维持原业务断言，将关闭看门狗从 UI 构建前移到 worker 启动后，修复基线在重 I/O 下也可复现的计时问题 |
| `tests/run_modular_release_qa.py`、`tests/resume_modular_release_qa.py`、`tests/run_restart_qa.py`、`tests/run_legacy_migration_qa.py` | 隔离 Windows EXE/安装器、原生更新/回滚、推理、重启和旧环境复用验收 |
| `README.md`、`packaging/安装说明.txt`、两份模块化文档及 `IMPLEMENTATION_STATUS.md` | 用户操作、发布维护、真实结果及中断恢复 |

主程序保留 UI、LLM、立绘、气泡、设置、语音桥接和更新管理；不包含 `services/gpt_sovits` 或内置参考录音。语音组件保持 `services/gpt_sovits` 与 `assets/audio/tts_reference` 原路径，暂作为单一组件版本 `v2ProPlus-cu128-runtime-1`。筛选后为 40,327 文件、10,037,222,548 原始字节；已签名测试 ZIP 为 6,219,221,474 字节，4 分卷。未改写推理或模型结构。

排除训练入口、数据准备、训练 filelists、WebUI/导出工具、缓存和日志，保留实际推理导入依赖及所选权重。没有冒险删除私有 Python 中可能被间接导入的依赖包；其内部可能仍含训练相关库，不能称为逐依赖裁剪到理论最小。

## 安装、迁移与日常操作

1. 主程序安装器及配套 `.bin` 全部在本地安装，GitHub 不通也不影响安装成功。完整离线包复用同一个 Inno 配置，另外提供可选 voice 组件。
2. 安装页可选择安装结束后打开语音下载面板。下载失败可跳过并继续使用主程序；未把不可用网络挂在安装器的必经步骤中。实际下载交接在主程序启动后完成，并非在 Inno 进程中下载十余 GB 资源。
3. 后续在“更新与语音资源”检查清单，再安装/修复；显示组件版本、大小、磁盘空间、源、速度、进度、剩余数据及错误。可暂停/保留进度、重试或明确删除缓存，也可导入签名 JSON 与完整 ZIP。
4. v0.2.0 首次使用 1.3.0 主程序安装器迁移：优先检测原 Inno 目录，保留目录选择。旧环境和 assets 不因仅安装主程序而被清理；原路径不可写时安装到新的用户目录。
5. 换目录后从资源面板选择可信旧安装目录，重启后免复制复用环境、模型和参考录音。保留旧目录。配置、日志、用户导入资源继续使用现有用户数据根；DPAPI 自动配置限同一 Windows 用户。
6. 主程序启动后后台检查 `main-from-<当前版本>.json` 和独立 `voice-manifest.json`。新版本弹窗包含版本、日期、标题、说明、大小及立即/稍后按钮。稍后关闭提示，程序继续运行。
7. 确认下载后校验分卷、整包、签名；独立 updater 等待主程序退出，检查实际基线，备份完整操作计划后替换。失败恢复旧文件；未提交事务下次启动先经独立 helper 恢复。语音卸载只删除清单登记且未被修改的文件。

## 下载与发布契约

附件、清单、API 使用三组独立源配置。普通源优先，`fallback_only=true` 代理只在普通源失败后参与；`enabled=false` 永久跳过该候选，不自动改回开启。公共代理地址在 JSON，不在核心逻辑，用户可编辑、禁用、排序。没有开发者 Token 或自有服务器依赖。

`.part` 和状态 JSON 保存目标哈希、大小、具体源和强 ETag；同源、相同内容标识才续传。严格校验 206 的 Content-Range/总长度/ETag；返回 200 截断重下。换源保守重下当前分卷，已验证完整分卷可复用。暂停是停止本次读取；重启后的续传必须重新满足 HTTP 条件。

远程清单只允许官方仓库固定结构的附件 URL；代理前缀来自本地配置，逐跳限制重定向。Ed25519 覆盖排序紧凑、ASCII 转义的规范 JSON payload，签名/公钥均为 Base64。32 MiB 清单上限和 100,000 文件上限覆盖当前实际运行环境；下载或导入内容须大小、SHA-256 和签名全部通过。

构建完整离线包、主程序安装包、独立语音包、增量包及签名单独步骤的可执行命令见 `docs/modular-updates.md`。主程序精确基线 inventory 生成仅含变化文件及显式删除操作的 ZIP；语音可用自己的 inventory 生成差异包。新主程序 Release 应附上现有 `voice-manifest.json`，可继续指向旧语音 Release，不重复上传未变化资源。

**生产前提**：维护者自行生成/保管密钥，公钥已内置正式构建；正式语音签名已由维护者在本机执行并通过验签。公开附件已备齐，所有旧QA二进制不得发布。未向代理提供生产私钥/Token，没有推送、创建 Release 或覆盖远端资产；线上验收仍待后续。

## 已有实际测试证据

| 命令/测试 | 真实结果与证据 |
| --- | --- |
| `.venv/Scripts/python.exe -B -m unittest tests.test_optional_voice tests.test_pipeline tests.test_desktop tests.test_session_restore -v` | 初期24项通过，57.867s；`work/stage-b-tests.txt` |
| 完整 unittest 回归（上次快照） | 323项通过，455.290s；`work/full-tests-verified.txt`。后续新测试不冒充已包括在此轮中 |
| 下载、边界、Qt与桌面专项（上次） | 41项通过，52.710s；`work/final-boundary-tests.txt` |
| 批量事务专项（上次） | 10项通过，2.433s；`work/linear-transaction-tests.txt`，先复现平方级日志写入再修复 |
| 异常语音配置、事务、桌面专项（上次） | 18项通过，16.023s；`work/final-safety-tests.txt` |
| `.venv/Scripts/python.exe -X utf8 -B -m unittest tests.test_update_entry tests.test_update_ui -v` | 本次11项通过，4.995s；`work/resume-lifecycle-green.txt` |
| 上述生命周期回归的修复前执行 | 等待超时仍重启、交接暂停仍启动两项均真实失败；另一个断言因 Windows 8.3 路径与解析全路径不同而失败，统一夹具解析路径后保留原断言意图；`work/resume-lifecycle-red.txt` |
| Windows冻结、Inno主程序/完整离线编译与隔离安装 | 上次两轮实际执行；`work/release-qa-130-v2/results.json`、`work/release-qa-v2.log`；中文/空格路径，无注册表和快捷方式 |
| 签名主程序包、等待父进程退出、Win32占用文件回滚并重启核心UI | 原生 EXE 实际执行，见同一 results.json；用户数据和修改过的默认立绘保留 |
| 完整离线包筛选后的真实 GPU 推理 | 通过，49.5s；70,400字节非静音PCM，32kHz，RTX4060 Laptop / torch2.7.1+cu128 / CUDA12.8；`work/release-qa-130-v2/tts-full.json` |
| 独立 updater 实际重启无害窗口隐藏探针 | 通过；`work/restart-qa/result.json` |
| 非默认旧目录免复制复用真实推理 | 通过；`work/legacy-reuse-qa/result.json` |
| 本次中断事务恢复 | 独立 updater 已成功恢复，204.26s；`work/release-qa-130-v2/recovery-result.json`、`resumed-results.json` |
| 本次最新源码冻结与主程序安装 | 客户端及独立 updater 冻结成功；`work/final-reviewed-build.log`。实际 Inno QAMode 编译、安装成功，主程序 setup 2,153,637字节 / bin 75,781,877字节；`work/final-reviewed-inno-install.log` |
| 本次最新安装版无语音核心验收 | 通过：UI、资源面板、入口、字幕与立绘事件，未安装语音、未朗读；`work/final-reviewed-build/core-main.json` |
| 本次最新 updater 原生重启 | 通过；`tests/run_restart_qa.py --work work/restart-reviewed-qa --updater work/final-reviewed-build/TachiTalk/TachiTalkUpdater.exe`，`work/restart-reviewed-qa/result.json` |
| 本次完整回归 | `.venv/Scripts/python.exe -X faulthandler -X utf8 -B -m unittest discover -s tests -v`：332项全部通过，395.212s；`work/full-tests-20261023.txt` |
| 加入密钥工具后的回归快照 | 同上 discover 命令，337项全部通过，377.104s；`work/full-tests-with-signing-20261023.txt`。之后补充构建许可证及便携去重 |
| 打包修复后的回归快照 | `.venv/Scripts/python.exe -X faulthandler -X utf8 -B -m unittest discover -s tests -v`：338项全部通过，376.938s；`work/full-tests-final-20261023.txt`。之后补充200错误清单切源回归 |
| 后补发布密钥工具与签名回归 | `tests.test_signing_setup tests.test_component_release tests.test_updates.ManifestTests`：10项通过，1.227s；`work/signing-setup-green.txt`。实际生成/解密临时QA加密私钥并签名/验证，QA文件随夹具清理；没有生成生产私钥 |
| 独立语音ZIP原生安装 | 40,327文件，实际安装成功1373.62s（约23分钟）；`work/release-qa-130-v2/voice-install-result.json`，非仅测试安装函数 |
| 独立语音ZIP安装后的实际推理 | 通过47.6s，模型就绪42.953s，首PCM0.485s；70,400字节非静音PCM，32kHz，原torch2.7.1+cu128/CUDA12.8/RTX4060 Laptop；`work/release-qa-130-v2/tts-downloaded.json`，拥有的服务正确退出 |
| 独立语音托管卸载和核心UI | 原生卸载成功1173.2s（约19.6分钟），核心UI/字幕/立绘/资源面板正常，语音未安装状态正确，旧文件sentinel保留，pending已清除；`voice-uninstall-result.json`、`core-after-voice-uninstall.json`、`resumed-results.json`（同一QA根） |
| 最终交付构建与主程序安装实检 | 通过，README/LICENSE/第三方说明逐个SHA匹配，实际编译与安装，核心UI无语音通过；`work/final-delivery-build/final-smoke.json`，setup 2,153,936字节 / bin 75,785,034字节；`work/final-delivery-smoke.log` |
| 清单回退修复后的最新安装版 | 通过，`work/verified-release-build/final-smoke.json` / `work/verified-release-smoke.log`；setup 2,153,936字节 / bin 75,790,206字节，说明与许可证哈希匹配，核心UI无语音通过 |
| 正常启动入口（非自检参数） | 最新安装版在无语音、无API Key、全检查源禁用的隔离用户目录真实启动，出现TachiTalk立绘及角色控制窗口；仅向该进程窗口发送WM_CLOSE后正常退出0。`normal_startup_and_clean_close=true`，同一final-smoke.json |
| 打包调用方回归 | 8项通过，0.198s；`tests.test_portable_package tests.test_component_release tests.test_release_resources`，`work/portable-docs-green.txt`。新客户端文档曾导致完整便携ZIP同路径重复（8项vs5个唯一项），真实RED后修复，也防止旧客户端重复携带语音 |
| 清单源验证后才接受HTTP200 | 原先200错误页使后备源未尝试已真实RED；本地HTTP回退、HTML/签名篡改拒绝、UI/下载/事务共36项通过40.769s；`work/metadata-fallback-red.txt`、`work/manifest-adapter-red.txt`、`work/metadata-fallback-green.txt` |
| 最终全部源码回归 | `.venv/Scripts/python.exe -X faulthandler -X utf8 -B -m unittest discover -s tests -v`：340项通过，366.764s；`work/full-tests-verified-release-20261023.txt`，进程正常退出0 |

第二轮早期321项曾有1失败+1错误：桌面3秒看门狗在重I/O下先于UI构建完成触发。已只读加载修改前 `4666ea0` 代码复现，修复计时起点后原两项通过；不能把该次失败称为全通过。PyInstaller曾提示可选 `tzdata` 未发现；Windows验收不能替代所有平台/时区场景。

本次 PowerShell 初次串联 GUI 安装器与核心自检时，shell 未等待 GUI 安装结束，随后的 EXE 尚不存在而失败。已核对 Inno 日志实际成功，再通过 Python `subprocess.run(..., check=True, timeout=90)` 等待核心自检并读取 JSON 验证成功；没有把初次 shell 失败记为测试通过。

密钥工具测试最初使用仓库外真实目录时遇到 WinError 5，Windows `tempfile` 在该权限错误下持续重试。已停止对应测试进程，保留 `work/signing-setup-red-diagnostic.txt`，使用受控夹具模拟仓库/外部签名目录；临时测试私钥只以加密格式写入被忽略的夹具并在测试后删除。没有绕过生成工具的生产路径校验。初次缺模块错误及夹具权限错误不计为功能RED；真正行为RED为“未生成加密文件/未拒绝覆盖或仓库路径”（`work/signing-setup-red.txt`），以及未提供本机密码入口（`work/signing-password-red.txt`）。

## 代码复核

- 正确性：追踪 desktop 启动、会话恢复、optional voice、资源按钮、client、下载与 updater 的直接调用，检查源全部失败、暂停交接、父进程未退出、错误基线和恢复分支。复现并修复父进程等待失败时重复启动、交接前暂停仍安装两项问题。
- 可读性：保留既有业务与 UI，下载、信任边界、文件事务、界面控制和构建分别成模块，没有引入通用更新框架。
- 架构：远程数据不能提供 shell 命令或信任根；UI 不启动解压/推理任务；独立 helper 从用户缓存运行，保持客户端/语音独立版本和文件所有权。
- 安全：检查签名、哈希、逐跳来源、ZIP inventory、路径穿越/链接检查、仅显式删除、用户资产保护、测试密钥隔离。生产公钥未配置会拒绝安装，不能视为已完成生产发布验收。
- 性能：检查有限请求重试、后台哈希/合并、数万文件日志写入复杂度；已用失败回归把逐文件全日志重写改为完整计划一次持久化。大包路径检查、备份和替换仍需数分钟，未宣称即时安装。
- 差异卫生：基线文件采用 CRLF 且 `.gitattributes` 设为 `-text`；使用 `git -c core.whitespace=cr-at-eol diff --check` 检查通过，保留原有换行。

## 最终执行状态

- 本地必需功能已实现并通过上述实际测试。当前没有未结束的QA安装器/推理进程；已检查当前及前一轮QA安装根均无pending。源码修改未提交或推送，建议建立本地开发检查点；不标记稳定。
- 正式公钥、生产构建与语音签发/验签已完成；线上Release/代理验收仍待继续，不能把本地测试通过描述为已公开发布或全平台兼容。

本次最新构建实检的可复现脚本保存在忽略的 `work/verified_release_smoke.py`；实际命令（项目根目录）：`$env:PYTHONPATH='D:\TachiTalk'; .venv/Scripts/python.exe -X utf8 -B work/verified_release_smoke.py`。它使用已有冻结产物，ISCC加 `/DQAMode=1 /DMainOnly=1`，以Python `subprocess.run` 等待GUI安装器，再验证离线核心和正常启动。原生完整包验收可使用仓库中的 `tests/run_modular_release_qa.py --work work/<新目录> --compiler '<ISCC路径>' --full` 复现；不要以稳定安装目录作为测试根。

## 18项需求与证据对应

| 编号 | 实际覆盖 |
| --- | --- |
| 1–3 无语音启动、基础业务、资源状态 | 最新冻结安装版 core-main.json；optional_voice、desktop、pipeline 回归。LLM通过本地模拟HTTP，未调用真实付费服务 |
| 4 UI发起资源下载 | Qt实际按钮 → 本地HTTP字节 → 签名/哈希验证 → 安装交接回归；完整语音ZIP原生安装链另列 |
| 5–6 中断续传、不支持Range回退 | aiohttp本地服务真实断流、保留part、带Range重连、200截断、错误Content-Range/ETag拒绝 |
| 7–8 切源、全部源失败后仍可用 | 本地下载源故障回退、显式禁用优先级测试、Qt错误后窗口/设置继续可用；公共代理线上能力未测 |
| 9 损坏拒绝 | 资源SHA、ZIP inventory、签名篡改和错误密钥拒绝，未修改原EXE |
| 10 主程序更新不下载语音 | 文件差异ZIP只含变化EXE和明确删除项；保留语音sentinel；更新与资源清单分别获取 |
| 11–12 更新介绍、稍后继续 | Qt弹窗实际字段及稍后关闭后主窗口仍可见；不会静默下载/启动安装 |
| 13 关闭主程序后独立更新 | 原生updater实际等待冻结父进程退出；最新源码另有等待失败不重复启动回归 |
| 14 失败恢复 | 实际Win32文件占用导致替换失败、恢复旧EXE并成功核心启动；进程中断的4万文件事务本次实际恢复成功 |
| 15 数据保护 | 用户配置/日志/导入资源事务回归；Inno重装保留旧环境、导入PNG及修改过的默认立绘；托管卸载保留变更/未登记文件 |
| 16 GUI不阻塞 | Qt心跳在后台检查与下载时继续触发；网络/合并/大文件校验由worker，解压/替换由独立helper执行 |
| 17 旧版迁移 | Inno重装旧环境sentinel；非默认目录选择、免复制复用、实际GPU推理通过 |
| 18 签名与哈希 | Ed25519签名/篡改/未知信任根、65,000条大清单、文件/整包/分卷SHA测试；正式release-1信任根、用户签发清单及原生updater坏包拒绝本次通过 |

## 尚未验证及风险

- 生产公钥已接入；尚无生产签名 Release 和真实 GitHub 大文件/公共代理端到端验收，本地 HTTP 故障注入不能证明公共代理可用或支持 Range。代理可能改域名、限流、断流，仍可禁用并离线导入。
- Windows 10、RTX50、干净系统、低权限/杀毒拦截、真实断电/磁盘硬件故障没有实机覆盖。只有当前 Windows11 / RTX4060 的证据。
- 用户经历权限/密码错误后，已确认自行生成密钥，公钥配置已接入。自动测试覆盖加密存储、目录预检、路径/覆盖拒绝、密码及签名验证；没有读取生产私钥，因此备份与真实清单的生产签名/验签仍需维护者操作。
- 新筛选语音已通过完整离线Inno和独立ZIP的实际推理；原有完整便携ZIP工具通过回归，本轮未再次压缩整个便携ZIP。Inno安装中的强制断电/取消恢复没有实机覆盖。
- 文件事务回滚已测，不包含“新版启动健康检查失败后自动回滚”协议。若磁盘满、备份损坏或长期占用使恢复失败，会保留备份和 journal 并停止自动重启，需人工处理。
- stage、备份和卸载备份目前保留，不自动删除；大资源的安装、恢复和卸载可能耗时数十分钟并占用额外磁盘。本次原生四万文件安装实测约23分钟，尚未优化成目录切换。不要在未检查事务前删除这些目录。
- 签名只证明发布来源与内容未变，不能替代维护者审查依赖、模型与第三方资源再分发许可。QA测试公钥信任的构建只作本地验收。
