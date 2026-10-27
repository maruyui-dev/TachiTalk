# v2.0.0 r6：v2ProPlus 完整训练包

本轮补齐初版训练工作台缺少的识别和人声分离权重，并让音频处理可以分步执行。主程序仍为正式版 2.0.0，配套安装 ZIP 使用 r6 文件名；没有推送 GitHub 或修改魔搭云端，没有覆盖桌面日常安装。用户另行明确授权后，仅调用既有脚本完成 release-1 生产签名，并用最终冻结更新器内置公钥验签通过；私钥和密码不展示、不进入资源包。

## 用户操作

1. 旧 r5 用户先同目录安装配套 r6 主程序；已有推理包继续复用，不重下稳定语音环境。
2. 在“更新与语音资源”主动下载完整训练包，沿用 GitHub / 魔搭双来源、原下载器和续传规则。未安装训练包不影响默认角色推理，未安装推理包时仍锁定推理表单并提示下载。
3. “模型训练”中导入音频副本，打开“音频处理与自动标注”。可选“切分并自动标注”“仅切分音频”“仅自动标注”“仅分离人声”，组合处理也可先分离人声。
4. 切分提供静音阈值、最短切分目标、单段最长时长、静音间隔和保留静音长度。仅切分不加载识别模型，标注留空供后续自动识别或人工填写；单段最长时长限制在训练支持范围内。
5. 所需权重由完整包内置，不再让用户选择 `.pt` / `.pth`。校对并保存标注后处理数据集特征、训练 SoVITS/GPT、试听并应用为桌宠语音。原始音频、标注历史和训练产物保留。

实际界面截图：`docs/designs/tachitalk-complete-processing-20261025.jpg`、`tachitalk-complete-training-20261025.jpg`。

## 资源与体积

| 项目 | 大小 |
| --- | ---: |
| 完整训练 ZIP | 1,993,028,270 字节，约 1.86 GiB |
| 解压后的训练文件 | 2,163,357,498 字节，约 2.01 GiB，30 文件 |
| 其中多语言识别权重 | 1,617,941,637 字节 |
| 其中 UVR 人声分离权重 | 63,454,827 字节 |

初版约 426 MiB 的包没有这些识别和分离权重，本包替代初版；不能把两包大小都加到最终用户安装体积里。训练数据、特征、检查点和个人模型另计。

保留三份 v2ProPlus 所需底模及训练工具，新增官方 Whisper large-v3-turbo 与 UVR HP2 权重和许可证。只提供 v2ProPlus 训练选项；Whisper 是音频标注模型。复用语音包原有 openai-whisper、PyTorch 2.7.1 + CUDA 12.8，没有添加第二套 CUDA 运行库，也没有升级依赖。模型来源、大小、SHA256 及补丁说明记录在资源内 `SOURCE.json`。

训练 ZIP：

`D:\TachiTalk\distribution\training-v2ProPlus-training-2\upload-to-modelscope\training-v2ProPlus-training-2.zip`

SHA256：`fbf1c456f82c5df70862799fdb2b94f45b303a54e91a344e04672344f060a013`

配套主程序：

`D:\TachiTalk\distribution\TachiTalk-v2.0.0-setup-r6.zip`

116,277,769 字节；SHA256 `ddce9b4ce5712b8c7f3cbae46208d12c816b75faca0dbcb161f67319260af345`。配套 `.zip.sha256`，ZIP CRC 通过。本机可运行构建在 `work/training-full-20261025/release/TachiTalk`，其独立验证配置复用项目语音目录，不进入安装包。

## 分发与安装

- 当前 ZIP 小于 2,000,000,000 字节，签名清单将整个 ZIP 作为一个下载对象；仍使用已有 `parts` 协议、Range/If-Range、来源锁及大小/哈希校验，没有另写下载器或改语音选源/续传规则。
- 补齐魔搭训练清单、ZIP及分卷的严格文件名映射，保留既有语音/主程序路径约束。训练清单独立验签，错误组件和错误签名拒绝。
- 正式上传文件只有 `training-v2ProPlus-training-2.zip`、`training-manifest.json`、`SHA256SUMS-training.txt`。上传到原魔搭仓库 `MaruYui/TachiTalk-Voice-Runtime` 的 master 根目录；同一组文件可放入 GitHub `maruyui-dev/TachiTalk` 的 v2.0.0 Release 附件。保留旧语音附件，不上传外层文件夹、unsigned payload、inventory、QA 程序或密钥。
- 配套上传说明及本机签名脚本在 `distribution/training-v2ProPlus-training-2`；生产签名结果记录在 `work/training-full-20261025/production-signing-result.json`。上传前必须确认 `upload-to-modelscope/training-manifest.json` 已生成并通过现有生产公钥验证；QA 临时签名只用于隔离测试。
- 本次生产签名及冻结产品公钥验证已完成，记录 `production-signature-verified.json`，上传目录恰有上述三个文件。最初当前环境缺少签名变量，控制台调用未生成清单；最后通过本机掩码输入框将密码仅传给原签名脚本的子进程环境，调用退出 0，未把密码写入命令行、文档或日志。
- 安装保护、锁、原子写入、事务备份与恢复、成功后的材料清理及自动重启保留。新增 ASR/UVR 权重也纳入个人修改备份保护。卸载训练包只移除未修改的托管文件，保留推理环境及用户项目/模型。

## 实际验证

- 52 项相关测试通过，20.079 秒，记录 `final-critical-tests.txt`；安装进度 5 项通过，11.126 秒，记录 `progress-transaction-tests.txt`。本轮未跑全量回归、未重下大型推理包、未调用付费 API。
- 真实仅切分测试处理带静音长片段及短片段，不选择识别权重，生成多个 WAV/空白标注，原文件字节和标注历史保留，旧特征标记失效。
- 真实离线流程用两条参考音频副本，其中一条混入测试背景音；每个工作进程禁止网络连接。内置权重完成分离、切分和日文识别（19.296 秒）、四步特征处理（63.547 秒）、SoVITS/GPT 各一轮训练（153.547 秒），训练模型输出非静音 32 kHz PCM。日志 `native-complete.log`、`native-results.json`、`actual-annotations.json`；小样本证明链路成立，不代表充分训练或完整音质验收。
- 最终冻结主程序/更新器 96 个应用代码对象、随包工作脚本与源码一致。正常产品入口 `--core-check` 通过。
- 最终冻结更新器在隔离目录安装本次完整 ZIP（17.750 秒）、自动清理并重启；使用的临时 QA 签名仅更换 QA 副本公钥，产品生产公钥不变。只复用桌面已安装语音环境的运行文件，训练权重从新装包读取，不修改桌面目录。冻结 Qt 页面真实完成分离、切分和标注，期间 738 次定时回调，UI 未加载 torch。
- 随后真实卸载、清理、重启及用户模型保留通过；运行环境关键文件前后哈希一致。记录 `frozen-final.log`、`frozen-results.json`，安装与卸载失败/恢复保障另有小夹具测试。
- GitHub/魔搭选源的训练清单验签、错误签名、文件路径与重定向范围通过相关测试；尚未代上传，不能将夹具结果写成云端附件已上线或公网下载已验收。

两处实测发现并修复的问题：

1. Whisper 整模型 `.half()` 使其要求 FP32 的 LayerNorm 报 `expected scalar type Float but found Half`；恢复原混合精度方式，保留 FP32 权重，由 transcribe 选择 CUDA FP16 运算。没有升级库或关闭校验。原失败记录 `asr-half-failure.log`，修改后同完整流程通过。
2. 连续安装/卸载复用旧进度文件时，上一笔事务的关闭计时器先触发并被运行中的新任务拒绝，旧标志又阻止新任务完成后自动关闭。计时器改为窗口拥有，在事务 ID 变化时停止并复位；先用 Qt 测试复现，再修复并在最终完整包冻结链路重验。原失败是窗口未退出，安装/卸载和清理已成功，不将其误写成安装卡死。未强杀任何安装，只正常关闭已结束的 QA 窗口。

本机为 RTX 4060 Laptop；RTX 50 系未实机重测，原稳定 torch/CUDA 栈保持。其他语言的识别质量及完整角色训练音质未在本轮做全面验收。

## 涉及文件与回滚

修改 `app/training/project.py`、`scripts/training_worker.py`、`app/ui/training_page.py`、训练资源下载卡片/提示、`app/updates/modelscope.py`、清单提示、`app/updates/install.py` 的权重备份范围、`app/updates/progress_window.py` 和组件打包清单；新增完整资源/许可证、相关测试及本文。没有改原推理包内容、默认模型或用户配置。

小型源码快照为 `work/training-full-20261025/before`，不含整套语音环境；本地原分支、HEAD 与所有原未提交内容保留。回滚可恢复对应快照或使用既有 r5 主程序；完整训练包通过 UI 卸载，用户训练项目保留。不要用 `git reset/clean` 或删除稳定语音环境来回滚。
