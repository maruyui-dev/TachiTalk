# v1.3.6 用户反馈修复验证（2026-10-24，v1.3.7测试包已交付）

## 基线与边界

实际目录 D:\TachiTalk；分支 feature/modular-updates，HEAD 4666ea0e1b3f255e4ee6276294e7582781f42414；stable-2026-10-22 对象 979a8fba7a18acaae7c579ed7795ddf75a08d9de、提交 8eb0d2b145ea065ba23f8035abb94ac0c9036956。开始时无 TachiTalk/Python 进程。所有既有未提交内容保留。小型源码快照、文件哈希与开始时状态在 work/bugfix-20261024/before、snapshot-hashes.json、git-before.txt；不复制语音环境或大包。

桌面原测试 ZIP 实测 77,983,417 字节、SHA256 8b6b0866b9b6aa854c941bce65559b324b7dc9d4d653b5a9d03344223baf475e。三张指定反馈截图均实际查看；另两张追加截图显示地球/旧云朵图标。截图中的资源映射、组件安装、LLM/TTS 尚未就绪仅为可见现象；未获得该电脑内部日志和配置。RTX 5070 Laptop 是环境信息，尚无证据认定 CUDA/显卡为原因。

## 初始分项记录

| 项目 | 已确认现象 | 根因假设与本机证据 | 缺失证据 |
| --- | --- | --- | --- |
| BUG1 神态 | 目标截图多个显式错误映射 | 源码隔离新用户、真实桌面入口及独立进程重启未复现，默认空 mapping；检查安装包携带数据/历史配置、控件初始化和实际 catalog | 目标电脑 resource_library.json/portrait-packs 配置的非敏感映射部分、实际运行版本/路径 |
| BUG2 聊天无声 | 目标试听成功但聊天仅文字 | 本机已定位未装组件时 prepare_optional_voice 将 auto_read=False 回填 UI，正常退出持久化，安装重启后继续关闭；试听不受 auto_read 限制 | 目标运行日志、朗读选项、服务启动/合成/播放结果；不是 RTX50 验收 |
| BUG3 开关不可见 | 目标“启用录音对话”只显示文字；用户补充 arrow_up/down.svg 路径不存在警告 | 已确认安装器 Excludes:"assets" 尾匹配误排除任意层 assets，原 qa-final 原生安装也缺整个 resources/control_panel/assets；冻结输出有文件但安装产物漏装 | 目标修复包复测 |
| BUG4 恢复默认 | 目标关闭重开未恢复 | 源码真实桌面/DPAPI/跨进程正常关闭和显式导出均暂未复现；继续冻结程序及写失败检查 | 目标日志中自动保存/恢复结果、配置目录、启动方式/Windows账户是否一致 |
| 检测跳滚 | 本机真实 Qt 复现开始 0→223、结束→499 | set_busy 禁用当前焦点按钮导致焦点落到屏幕下方，QScrollArea 自动滚动 | 无需目标日志即可修复 |
| 魔搭图标 | 网络卡片为地球，推荐卡片残留云朵 | 同一服务应使用一致魔搭标识，待统一 | 无 |

## 当前修复与验证

- 中间全量494项/515.892秒通过；最终全量495项/498.672秒全部通过，见 full-tests-final.log，原生Inno用例实际执行、没有跳过。新增原生用例在最终发现集合中完整纳入。最终命令：在D:\TachiTalk运行 `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v`。
- QA执行错误记录：最初辅助冻结程序重建和原生QA启动重叠，辅助输出目录被替换过程中出现 QtCore DLL 导入失败；用户看到了该QA错误窗口。此为代理测试编排错误，不是目标用户产品新证据。失败日志 qa-build-final.log、native-qa.log 保留；最终改为 qa-freeze-verified 独立输出目录，沿用产品构建的干净DLL搜索PATH、辅助程序控制台入口（异常进入日志），构建成功后写完成标记再启动验证，避免重建与使用重叠。产品 release-final/TachiTalk 输出、日常安装及稳定语音环境未受此错误覆盖。最终冻结结论只使用后续成功记录。

- BUG2：VoiceSettings 增加与 provider/URL 绑定的临时不可用状态，snapshot 为本轮运行返回安全文字降级，不修改用户朗读偏好；prepare_optional_voice 只更新可用性，desktop 不再把临时 false 回填 UI。缺组件→关闭保存→安装状态就绪→独立进程启动无须试听可恢复 TTS 请求；显式 false 保持 false。6项进程测试原 5PASS/1FAIL（47.056秒，UI偏好被清）；修复后连同3项原文字降级测试9项50.876秒通过。组件就绪是夹具，不冒充实际模型安装/GPU验证。
- BUG3：用户随后提供目标 arrow_up/down.svg 路径不存在的完整警告，结合旧 qa-final 安装目录确认是安装器漏装。Inno [Files] 的 Excludes:"assets" 匹配任意层级同名目录；改为根锚定 Excludes:"\assets"，保留根 assets 的 onlyifdoesntexist 用户图片保护，同时安装 resources/control_panel/assets。官方依据：https://jrsoftware.org/ishelp/topic_filessection.htm （Excludes）。新增 tests/test_installer_assets.py 在隔离目录实际编译/运行同一安装脚本，四个 SVG 原均缺失（RED 1项/4子用例，2.712秒）；修复后全部安装且用户同名图片未覆盖。与UI/可用性合计5项3.222秒通过。此前曾验证缺图时文字可点击而图形消失，并试验自绘替代；获得安装证据后撤回该替代，最终没有新增自绘类、没有修改业务控件/原QSS。旧原生QA只验证窗口可加载，未断言图标文件完整，历史“核心UI通过”不能代表此项已覆盖。DPI/最终冻结结果待补。
- 魔搭标识：网络卡片和推荐卡片统一使用 https://modelscope.cn/home 页面引用的官方favicon（https://g.alicdn.com/sail-web/maas/2.13.170/favicon/128.ico）；本地 resources/control_panel/assets/modelscope.ico 随资源复制。没有运行时网络依赖，推荐卡片去掉旧云朵的橙色视觉。
- 测试产物使用 v1.3.7、“配置与语音修复验证版”、独立 Test AppId/默认安装目录，避免不同字节仍叫原 v1.3.6 包；原包不覆盖。不是正式 Release。

- 检测跳滚：切换 busy 前将焦点留在当前滚动页面，避免 Qt 向下寻找可聚焦按钮。保留按钮可用状态及业务判断。tests/test_ui_bugfix_regressions.py 使用真实 Qt 点击、异步检测夹具，验证开始与完成、顶部与非零滚动位置。原测试 223 != 0 失败；修复后 1 项通过，0.776 秒。证据 red-scroll.log、green-scroll.log；不是公网测速记录。
- BUG1/4 独立进程用例由新 tests/test_fresh_user_regressions.py 验证，不用同进程重建代替重启；全部6项纳入最终全量通过。源码和冻结新用户实际映射/渲染、显式保存与正常关闭恢复均通过，不改变目标尚未复现的结论。
- 最终原生/冻结：native_qa.py 成功编译独立Test安装器及不注册/不建快捷方式的QA安装器，原生安装在 native-qa-final/主程序 测试，所有界面SVG和官方ICO字节与冻结输出相同；实际产品TachiTalk.exe --core-check通过。QA辅助exe的 app.paths/desktop/control_panel/voice_settings/components/session_controls/update_controls/update_network 冻结代码对象与交付产品相同，辅助exe不进交付包。通过真实FROZEN路径和独立LOCALAPPDATA运行10个全新进程；实测DPR1.0/1.25/1.5，四种indicator状态非透明可见、勾选/未勾选图像不同，网络检测前后scroll均0。保存/正常关闭后进程恢复UI、设备、AI配置、自定义两项“欣慰”映射和实际渲染；空配置全自动及实际“平常/开心”各自PNG、缺组件→模拟组件就绪后重启朗读偏好均通过。原生 verification.json 的 ok=true。组件就绪/网络是显式夹具；不代表完整语音下载安装或目标GPU验收。
- 本机实际语音：独立空闲端口及 work/bugfix-20261024/live-tts 运行目录，读取原稳定服务环境，未升级/复制环境。真实 monitor_voice_services 自行启动 TTS，82.594秒后真实就绪；没有打开试听页，随后共享对话 pipeline 将确定性的日语/中文LLM夹具送入实际 GPT-SoVITS、实际默认音频输出设备（32000Hz/单声道/16bit），spoken=true，欠载0，首块约0.511秒、到播放约0.590秒。测试87.032秒结束，只关闭本次拥有的服务。实际GPU为 RTX4060 Laptop、torch2.7.1+cu128、CUDA12.8；未调用付费ASR/LLM，不能冒充目标RTX5070或真实线上LLM/ASR验收。证据 live-voice-result.json、live-voice.log、live-tts/service.log。

## 目标电脑仍需确认

- BUG1/4：本机源码跨进程暂未复现，继续最终冻结测试；用户新增日志没有自动保存/自动恢复结果，尚不能判断是否读取同一数据目录、保存失败或历史自定义配置。不要重置目标配置。请保留目标 %LOCALAPPDATA%/TachiTalk 下原文件；后续仅需不含API Key的保存/恢复日志与资源 mapping 部分、实际启动EXE路径。
- BUG2：旧版已保存的 auto_read=false 与用户主动关闭无法区分，修复版不会擅自强开。目标复测先明确确认“自动朗读回复”的选择，再在未进入试听页时验证首次聊天与正常重启聊天。新安装的默认偏好不会再被临时降级覆盖。
- 无目标实机证据，不声明已完成 RTX5070 兼容验收。

## 交付与最终状态

- 测试包：D:\TachiTalk\work\bugfix-20261024\delivery\TachiTalk-v1.3.7-config-voice-bugfix-test-main.zip；77,484,153字节；SHA256 `089e61c135b97eb5852593d5685ef25e08c2edb1e39ce4bc676c866d28b3d622`；同目录.sha256.txt。ZIP CRC、成员、冻结产品/原生安装同字节、生产公钥/来源配置和main gate核对通过。辅助QA程序/测试代码未进入产品PYZ或安装包，精确基线另存main-1.3.7-config-voice-bugfix-test-inventory.json。
- 桌面复制被OS PermissionError拒绝，未再次尝试绕过目录权限。使用项目内交付路径。失败package.log与成功package-final.log均保留，原桌面v1.3.6包大小/哈希复核未变。
- 最终分项：BUG2本机缺组件覆盖偏好的确证缺陷已修，目标是否同因仍需核对；BUG3图标漏装已证实根因并修复；下载检测跳滚和魔搭两处标识已修；BUG1/4本机暂未复现，已做源码/冻结/跨进程验证，目标仍需证据，未擅自重置已有配置。RTX5070未验收。
- 独立审查final-review.md无剩余业务/安装规则阻塞；最终Git核对所有开始时脏条目仍在，HEAD/stable标签对象和解引用与基线完全相同，无提交/推送。control_panel.py与原QSS和本轮before哈希完全相同。测试程序与本次拥有的TTS服务均已结束。

## 不变约束

不重新接入 Cloudflare；保留新任务真实 GitHub 首字节 ≤3 秒/≤1KiB 探测、严格 <250ms 规则、任务来源锁和普通续传缓存、手动切源先停再清本任务。固定魔搭 main-latest.json 静默检测及独立 main_thread 不变。未改云端资源、稳定标签、信任链或 GPT-SoVITS/PyTorch/CUDA 环境，未读取生产私钥、未覆盖日常安装、未清用户配置/下载缓存。
