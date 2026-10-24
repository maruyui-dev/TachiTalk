# RTX5070反馈接续合并与1.3.10验证记录

日期：2026-10-24；原开发电脑项目D:\TachiTalk。输入为用户携带的RTX50_TECHNICAL_COMPLETE_20261024.md、RTX50_FIX_HANDOFF_20261024.md、RTX50_OLD_PC_CODEX_PROMPT_20261024.md。文档中的新电脑结果作为外部历史证据，不冒充本机执行；清理新电脑AppData的历史授权不延伸到本机。

## 证据与问题分层

| 问题 | 新电脑报告 | 本机接续结论 |
|---|---|---|
| 启动即有错误显式映射 | 旧AppData已有平常/开心→欣慰等映射；独立安装目录曾共享它 | 冻结路径原实现确实指向同一AppData，路径/旧语音选择隔离回归先失败；最初错误映射如何写入仍不确定，不归因GPU |
| 恢复默认后重启复发 | 资源页只换内存，独立资源文件未保存 | 本机两种跨进程路径均先失败；确认磁盘仍旧映射，补library.save()后下拉、磁盘、实际PNG、重启一致 |
| 试听可用但聊天无声 | 已存false保留，安装完成没有一次性启用协调，monitor按auto_read决定TTS预检 | 新要求明确安装后开启本地GPT朗读一次；本机先失败后合并协调器，并验证真正模型加载和播放，不设置假的service_ready |
| 数据跟随程序目录 | 用户明确要求每个程序目录独立，不迁移旧AppData | 冻结使用EXE旁user_data；源码_qt_runtime_tmp不变。无自动迁移/旧AppData回退；DPAPI不变 |

## 合并方法与保护

- 开始核对分支feature/modular-updates，HEAD4666ea0e1b3f255e4ee6276294e7582781f42414；stable对象979a8fba7a18acaae7c579ed7795ddf75a08d9de、提交8eb0d2b145ea065ba23f8035abb94ac0c9036956。原大量脏文件保留；开始未发现TachiTalk/Python运行进程。
- U盘没有配套source-changes ZIP，因此提取技术文档唯一diff附录，得到16文件代码/测试补丁。git apply --check有4文件失败；严格逐段比较发现所有hunk的实际行内容均唯一匹配，冲突来自原文件CRLF差异。按原换行合并并保留本机1.3.8已有修复；未强制apply或整目录覆盖。
- 小型可恢复快照work/rtx50-merge-20261024/before、snapshot.json、git-status-before.txt、merge-context.json；未复制稳定大环境、读取私钥或迁入新电脑session/Key/设备号。
- 新电脑1.3.9已有不同字节测试产物，本机采用独立1.3.10/TestBuild身份和全新输出目录。没有覆盖日常安装、关闭用户程序、清AppData或下载缓存；事务故障仅用临时小夹具。

## 实现

1. SettingsControls.reset_current资源页明确重置后调用library.save()，写成功后才提示成功；普通启动保留自定义。写失败仍报告并保留原磁盘文件。
2. app.paths冻结DATA_ROOT改为PROJECT_ROOT/user_data；ensure_data_root真实创建/写入探测。bootstrap保留安装锁优先及真正遗留恢复，在正常启动阶段检查可写；失败给出路径/错误并退出，不换AppData。
3. VoiceInstallControls在session恢复及组件可用性处理后、worker启动前创建并检查；Qt每3秒只检查关键文件。pending/真实占锁时等待；组件缺失只设置有效运行降级，不回写UI false。完整本地安装首次识别/缺失转完整/安装代变化后启用本地GPT朗读一次，不强制切换其他provider；session成功后再写安装代标记。TTS真实就绪、预检、重试、合成、播放仍由原服务链路负责。
4. Inno排除根user_data，保留根assets用户图片保护和嵌套UI assets安装。便携枚举排除user_data且按大小写折叠匹配，TEMP集合也统一为temp，避免大小写变体带出私有目录或回归原缓存排除。
5. 按携带补丁在requirements-build.txt补NumPy1.26.4作为新建主程序测试环境依赖声明。本机已存在NumPy2.5.3，未为合并更换现有环境；完整回归和冻结按实际本机环境验证。语音Python、torch2.7.1+cu128/CUDA12.8、模型不变；未安装可选Whisper。

## 审查追加修复

- 8,001字节深嵌套JSON可让新协调器构造时抛RecursionError；补先失败回归，纳入保守读取失败处理，原字节/用户偏好保留，不崩溃、不静默重建。
- session成功而安装代标记写失败、或者session本身失败时，原重试会再强开用户刚关闭的朗读。两个场景均先失败；分开记录本进程已应用的安装代和已保存的安装代，重试保存当前选择/标记，不重复覆盖UI；缺失状态在早退前清两标记。
- Windows大小写user_data和TEMP回归先失败后修复；没有改变动画、滚轮生产逻辑。携带的Qt6.12测试等待调整保留，所有原断言仍在。
- 独立审查work/rtx50-merge-20261024/review.md无剩余阻塞。并行全量曾因审查补修中止并重新启动，只终止经路径/命令/父子关系核实的本轮测试进程；中间日志保留，不计作最终通过。

## 本机实际验证

- 修复前路径/打包6项行为失败；首次命令有4项测试类名拼错，属执行错误，不计作行为RED。更正后恢复默认两条路径、安装激活两项、重置写失败反馈共5项全部按行为失败，详见red-behavior.log。审查追加RED分别见red-review.log、red-session-retry.log、red-private-case.log和red-temp-case.log。
- 主定向42项173.358秒通过；审查/路径/事务定向22项3.449秒通过；最终便携6项0.246秒通过。最终全量519项614.999秒，OK，无失败/错误/跳过。用户要求不再下载测试时，本轮下载组已结束，之后未追加或重跑下载测试；不下载真实6.2GB资源。原电脑旧502项/新电脑报告514项不替代本轮结果。
- 最终产品和QA辅助程序分开冻结，干净PATH、成功标记后才启动。10个相关模块的代码对象与产品相同；实际原生Inno安装/产品核心自检/四SVG和ICO字节通过；包不带开发user_data，安装保留已有user_data。
- **22个独立冻结桌面进程**通过：DPR1/1.25/1.5的实际四态indicator、初次/重开默认与PNG、两种重置路径持久化、自定义/AI/设备/UI恢复、语音安装后启用及后续主动关闭、busy/保存失败不消费、不同目录隔离、删除本次隔离安装夹具再复制为新用户。实际组件完整性与网络在此是明确夹具，不冒充完整语音安装或公网测速。
- 真冻结bootstrap遇user_data同名文件阻止目录创建时返回1，明确报告真实FileExistsError/路径，不回退旧AppData。读取共享旧AppData的哨兵字节保持不变。未冒充NTFS ACL权限实测。
- 最终实际冻结updater在真实独立进程持锁时返回2、不覆盖结果/journal；释放后恢复原文件；坏备份失败保留原目标/journal及诊断。第一轮夹具漏放安装身份文件，被正确拒绝为非安装目录；补齐夹具、改用全新transaction-qa-final后通过，没有修改业务以绕过身份校验。
- **本机RTX4060真实语音**：隔离成功保存边界、实际完整组件，从auto_read=false检测到true，检测时TTS ready仍false；原monitor44.203秒后真实就绪，未进试听，固定日文/中文字幕LLM夹具经真实聊天pipeline合成和默认设备播放，spoken=true、32000Hz/单声道/16bit、欠载0。48.344秒结束，仅清理本次拥有服务。真实DPAPI/重启另由桌面进程验证，不把此探针的保存边界当作真实session保存证据。

## 安装代和迁移边界

- 安装代为组件版本+component-version.json mtime_ns；legacy缺版本文件使用legacy标记。它是偏好事件，不是签名证明；触碰mtime可能重新触发，无可观察变化的legacy原地重装无法辨别。
- session和安装代标记是两个独立原子文件。已修同进程失败重试覆盖手动选择；若标记持续失败后退出，下一进程仍可能将旧标记视为未处理，不能声称跨文件、跨重启严格恰好一次。
- 损坏标记保守保留偏好和文件并记录诊断；用户可显式排查。不迁入新电脑用户数据；旧电脑现有AppData保持原样。新数据规则下要保留旧配置，必须由用户明确选择加载/复用，不偷偷迁移。
- 修正出发时文档：实际安装器名是TachiTalk_main_setup.exe；当前离线导入需要完整ZIP，**不支持直接导入四分卷清单**。本轮不新增分卷导入功能，不修改签名/清单、不重新哈希整套6.2GB语音材料。

## RTX5070历史报告与未完成项

携带文档报告：Windows11/RTX5070 Laptop、torch2.7.1+cu128、CUDA12.8保持；真实模型加载18.203秒、夹具聊天合成和Realtek播放成功；514项、17冻结QA及Inno通过。这些是新电脑历史结果，本机没有重新执行RTX5070硬件探针。

仍需目标电脑：真实冻结用户首次完整签名语音安装、安装后首次/重启聊天、用户真实付费ASR/LLM全链路。最初旧错误映射的写入来源仍未证实；不能归因GPU或宣称整个RTX5070兼容验收完成。Cloudflare移除、GitHub严格<250ms/最多3秒1KiB、来源锁/续传/手动切源、魔搭固定静默main feed及独立main_thread、签名公钥均保持。

## 最终交付

交付目录：`D:\TachiTalk\work\rtx50-merge-20261024\delivery`。安装版和便携版二选一，均为1.3.10独立测试身份，不含语音runtime/模型；ZIP CRC/成员/生产公钥和渠道配置一致性、无QA模块或私有user_data通过。没有发布正式Release。

| 文件 | 字节 | SHA256 |
|---|---:|---|
| TachiTalk-v1.3.10-rtx50-feedback-test-main.zip | 77,504,257 | d70cb6005ec8cfbd23f3c49007db519068688c879efb9d9e08510e75e04b1146 |
| TachiTalk-v1.3.10-rtx50-feedback-test-portable.zip | 102,451,086 | d9c0eb636d2b1bb9f29af1c4e529ededae541e34c58e7b26aae671837822ec6c |

配套.sha256.txt；小型源码接续包TachiTalk-v1.3.10-rtx50-feedback-source-changes.zip，包含相对本轮开始脏工作区的before/after、changes.patch及逐文件哈希，不是相对干净HEAD的补丁。先检查上下文，不整目录覆盖。证据docs/release-evidence-1.3.10-rtx50-feedback；结束HEAD和stable对象/提交保持，原脏条目仍在。未提交/推送、未改云端/信任链/稳定语音栈。
