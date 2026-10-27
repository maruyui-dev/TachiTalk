# 模块化安装与更新实施状态

## 2026-10-26 v2.0.0 r7：修复r5语音安装长路径失败（本地交付，未发布）

- 用户报错为已结束的failed事务，约314.884秒后失败；restarted=true仅代表失败后重开原程序。用户暂存文件267字符、最终204字符，基线有59个同类超长暂存路径。真实Windows传统路径限制进程和已发布代码一致的r5冻结更新器均复现同一文件FileNotFoundError；未访问目标用户电脑，未核实目标注册表或冒称目标已安装成功。
- 安装/备份/恢复/卸载/精确清理统一使用Windows扩展路径，不要求用户改系统策略；签名、哈希、路径限制、锁、同步原子替换和恢复保护保持。失败后重启不再覆盖失败阶段/文件/计数，仍保留自动清理和启动。新成功任务不删除旧失败的无提交标记备份。
- 52项相关关键测试20.943秒通过；冻结96应用代码对象/生产公钥一致、实际主入口核心检查通过。冻结r5失败后，在相同隔离目录复用同一缓存由新更新器安装、清理和重启探针成功，个人文件/旧失败备份保留；没有全量回归、重下大型语音包或覆盖日常安装。
- 交付distribution/TachiTalk-v2.0.0-setup-r7.zip，116,267,943字节，SHA256 `d888db26f8653b43c254506d0652c8289c29fa0d909895023d3ad56065a30eec`，版本仍2.0.0，保留r6完整训练UI；未上传GitHub/魔搭。r5用户选择原目录覆盖主程序，再由UI安装/修复，保留原缓存及事务。证据/小型快照work/long-install-paths-20261026，详见docs/release-2.0.0-r7.md。原HEAD/脏修改保持，未读私钥、未改云端/语音环境；r6已签训练上传包不变。

## 2026-10-25 v2.0.0 r6：完整开箱训练包（本地验证与待上传交付）

- 按用户新授权补齐 Whisper large-v3-turbo 多语言识别和 UVR HP2 分离权重、许可证；原生页面提供仅切分/仅标注/仅分离/组合处理及切分参数，无需手选模型。仅v2ProPlus训练，复用原PyTorch2.7.1+CUDA12.8，不升级依赖或复制另一套语音环境。只装主程序、只装推理资源的边界保持。
- 完整包30文件、解压2,163,357,498字节，ZIP1,993,028,270字节；SHA256 `fbf1c456f82c5df70862799fdb2b94f45b303a54e91a344e04672344f060a013`。交付distribution/training-v2ProPlus-training-2/upload-to-modelscope，沿用原下载器，单ZIP作为一个下载对象；补齐魔搭训练清单/归档映射，GitHub/魔搭选项与原语音续传规则保持。用户明确授权后，仅调用既有脚本完成release-1生产签名，最终冻结更新器内置公钥验签通过；密码仅在本机隐藏输入，不展示密钥或写密码文件，不上传云端。上传目录ZIP/签名清单/校验文件三项齐全，记录production-signing-result.json及production-signature-verified.json。
- 真实离线两条音频完成分离/切分/日文标注19.296秒、四步特征63.547秒、两阶段各一轮训练153.547秒，新模型非静音合成成功。52项相关20.079秒、安装进度5项11.126秒通过；未全量回归或重下推理大包。修复Whisper整模型半精度破坏LayerNorm的问题，保持其原混合精度方式。
- 最终冻结96应用代码对象/随包脚本与源码一致、正常主入口核心检查通过；完整训练ZIP隔离安装17.750秒、清理与重启，复用桌面语音环境只读完成实际Qt处理（738次回调），卸载保留个人模型，生产公钥和原运行文件不变。另修复旧成功事务关闭计时器影响下一笔事务的问题，保留原失败证据，不把已成功安装的窗口滞留误写为安装卡死。
- 配套distribution/TachiTalk-v2.0.0-setup-r6.zip，116,277,769字节，SHA256 `ddce9b4ce5712b8c7f3cbae46208d12c816b75faca0dbcb161f67319260af345`，版本仍2.0.0，未发布；旧r5需更新主程序才能使用本次UI。小型快照/证据work/training-full-20261025，详情docs/release-2.0.0-r6.md。未覆盖桌面安装、未改云端、原HEAD和脏修改保持；RTX50及其他语言质量未实测。

## 2026-10-25 v2ProPlus 原生训练工作台（本地完成，未发布）

- 侧边栏“模型训练”，原生Qt接入音频副本导入、可选UVR/Whisper处理、标注校对、四步特征、SoVITS/GPT训练、试听及应用到现有桌宠TTS；仅v2ProPlus。缺推理包锁定推理页并引导下载，训练扩展不阻止已有默认推理。重任务在私有Python子进程，UI不加载torch；实际进度/日志、保存后停止及续训可用，运行中关闭提示等待保存。未提供的Whisper/UVR权重需本机选择，实际处理质量未验收。
- 独立training组件只拥有services/gpt_sovits/training，复用已有推理环境；支持当前应用训练目录+外部旧运行环境，接入签名安装/修复/卸载、清理和重启，保护个人项目/音频/模型及修改过的底模。PyTorch2.7.1+CUDA12.8和稳定语音环境不变，未读生产私钥。训练增量25文件481,956,992字节，未签名本地ZIP446,403,974字节，SHA256 `a04987d9003fbb411b02d7a24753ee1c5f685857953d70b7e3b3b7aa1a1c9f72`；不是正式在线包。
- 实际两条参考音频完成四步特征、SoVITS/GPT各一轮100批次，新模型非静音推理32kHz/1.18秒，现有LocalTTSService应用后32kHz/1.14秒；保存后停止与恢复训练49.109秒成功。修复嵌入Python导入、检查点目录、GPT配置数值类型及有范围的WindowsPath检查点允许项；保留weights-only安全加载。RTX4060实测，不冒充RTX50或音质验收。
- 相关44项、58项、34项、兼容40项分别通过，组间有重叠；末次任务终态Qt显示7项9.557秒通过。116项关联检查曾有1个旧助手回收单项失败，定向重跑通过但一次性原因未确定，不宣称最新全量全绿。冻结隔离主程序独装/推理独装/旧环境复用、GPU私有工作进程及响应性、小签名训练包安装/清理/重启/卸载/保留用户模型通过；详情docs/training-workbench-v2proplus.md及work/training-ui-20261025。
- 最后构建96个应用代码对象/随包脚本与源码一致，两个真实冻结Qt进程验证任务成功/失败/停止终态，正式主入口离线核心自检通过。实际JPG见docs/designs/tachitalk-training-native-20261025.jpg及tachitalk-inference-locked-20261025.jpg；可运行本机验证构建work/training-ui-20261025/release/TachiTalk/TachiTalk.exe，隔离配置复用项目原语音环境，无新修订安装器。
- 小型快照before、原HEAD/所有脏修改保留，未覆盖桌面日常安装、未重下大型语音包、未跑全量回归。当前训练开发没有推送GitHub；已公开r5仍是此前安装优化版本。

## 2026-10-25 r5 GitHub 同步（用户明确授权）

- 已将经过验证的r5源码正常快进推送到公开main，提交 `1744e5cd2183e4775ee4055fbc6f3ea9c9e1b74e`。使用独立Git索引组合r5文件，87个冻结应用模块及随包界面资源与所选源码核对一致；没有提交正在开发的训练工作台、训练资源或用户数据。本地原分支、HEAD及未提交修改保留，未另建/克隆项目。
- 已在既有正式版v2.0.0 Release新增 `TachiTalk-v2.0.0-setup-r5.zip` 和配套 `.zip.sha256`，GitHub服务端大小116,185,200字节、SHA256 `4eda0f1feedb149ff3cb43bc8deab576382d3f743de3e60560b3226ef7d76fad` 与本地一致；更新推荐说明，原5个附件及v2.0.0标签保持。
- 发布页 https://github.com/maruyui-dev/TachiTalk/releases/tag/v2.0.0 。版本仍2.0.0，旧同版本用户需下载r5后覆盖主程序；已有语音无需重装。只使用GitHub现有凭据完成授权发布，未读取生产签名私钥，未操作魔搭。发布证据work/github-r5-20261025；后续训练开发不属于本次r5发布。

## 2026-10-25 正式版v2.0.0 r5：精简安装阶段，保留清理与重启

- 按用户追加要求将正常安装收敛为准备安装、安装文件、清理材料、重启；解压时完成大小/哈希校验，新文件fsync后同卷原子移入，取消独立逐文件重读和第二次整文件复制。普通旧文件优先硬链接恢复快照，不支持则同步复制；模型/参考音频独立备份、签名/归档校验/路径限制/锁/持久事务/恢复及用户数据保护保留。r4自动清理和解锁后自动启动保持。
- 实际桌面r4事务只读确认成功，27分56秒；逐文件重读348.044秒，替换976.386秒，为主要已定位耗时阶段；替换内部复制/fsync/路径检查未单独计时，不归因GPU或杀毒。自动清理40,335文件、22,490,836,790字节（20.95GiB）完成，没有干预运行中安装。
- 关键41项12.839秒、另真实硬链接1项0.082秒通过；128文件32MiB单次隔离比较新装2.293→1.207秒、覆盖3.333→1.821秒，stage完整副本33573029→0字节。最终冻结真实小签名包安装、精简阶段、清理132文件/66969字节、自动重启/助手回收、启动继续中断清理、离线Qt核心及11代码对象一致性通过。没有全量回归、重下语音或完整大包耗时复测。
- 版本保持2.0.0，交付distribution/TachiTalk-v2.0.0-setup-r5.zip，116,185,200字节，SHA256 `4eda0f1feedb149ff3cb43bc8deab576382d3f743de3e60560b3226ef7d76fad`；ZIP CRC通过，原r4包保留。小型快照/证据work/inline-extract-20261025，详情docs/release-2.0.0-r5.md。HEAD和原脏工作保留，未发布云端/改稳定语音栈。

## 2026-10-25 正式版v2.0.0 r4：安装成功后自动清理

- 在签名组件完整提交后自动清理本任务下载分卷/合并ZIP、stage和普通backup，再重启主程序；清理阶段有真实进度。保留实际环境、个人数据、其他下载任务、外部离线ZIP以及用户修改过的默认模型/参考音频备份。
- 小型持久任务支持崩溃后由独立更新器继续清理；清理失败独立记录，安装仍成功，避免重启循环。启动后延迟回收旧更新器副本，跳过新交接及运行中EXE；不强杀，不清无标记历史事务或此前移出的desktop-cleanup材料。
- 35项相关测试10.142秒通过，新增启动路由1项0.541秒通过；实际Windows占用/目录联接/路径越界/回滚/用户数据保护通过。最终冻结小签名包真实安装后删除261文件92,294字节，自动重启、旧助手删除及中断清理恢复通过；冻结核心Qt和9相关代码对象一致性通过。没有全量回归、重下语音大包、付费API或覆盖日常安装。
- 版本仍2.0.0，交付D:\TachiTalk\distribution\TachiTalk-v2.0.0-setup-r4.zip，116,179,318字节，SHA256 `8d02db72e8753ecb29452b9af1607cceafe062044a1700a3206a852860bc2ed7`，配套校验文件；ZIP CRC通过。未发布云端/GitHub，未读生产私钥或改稳定推理环境。小型快照及证据work/auto-cleanup-20261025；详情docs/release-2.0.0-r4.md。

## 2026-10-25 正式版v2.0.0 r3：独立安装进度、分段回复与日志降噪

- 实际 D:\桌面\TachiTalk 的原安装已于13:05:14成功，pending清除，主进程44488运行；40,327文件/约10.04GB，从锁文件创建到成功34分49秒。文件时间支持已完成，历史更新器PID/CPU/IO和精确阶段耗时不能回补；不认定GPU/杀毒软件卡死。原冻结代码无逐文件巨大journal重写。
- 新独立Qt更新器显示真实阶段、文件/字节计数、阶段百分比、当前文件、总/阶段耗时；心跳与实际进度时间分离，长时间不推进/进程退出/恢复失败可诊断。再次启动只打开原事务只读窗口；无强杀取消，成功自动重启。小型进度快照节流，签名、哈希、备份、锁、fsync及崩溃恢复保留。
- profile确认小文件重复路径解析/元数据检查为主要成本，合并检查并保留逐层重解析点及越界拦截；256文件同盘单次8.089→5.733秒（新版含进度），不承诺完整10GB安装耗时已解决。
- 复现并修复短续问回落2组报错、非流显示合并组边界和桌面同泡累计；提供32组有界自然分条，同组token更新、异组独立气泡，12组真实Qt完整交付，记忆仍按完整一轮保存。默认日志隐藏聊天正文、频繁状态、切页、自动保存/恢复和性能细节，保留重要INFO/警告/错误/堆栈及遮盖。
- 关键44项22.706秒通过；GUI收尾后4项5.364秒通过。最终冻结核心Qt、实际等待/只读重入/恢复/签名小归档安装/失败可见/自动重启均通过；17相关代码对象与最终源码相符。未全量回归、未重下语音、未付费API、未覆盖日常安装。
- r3包116,161,663字节，SHA256 `9b67aaf8f418ce25a55b29d4e93bd2fb42c885d8eaa8f130ff9d7dd7b3c19318`；路径work/install-progress-20261025/delivery/TachiTalk-v2.0.0-setup-r3.zip。版本仍2.0.0正式版，原未提交内容/HEAD保留，不发布云端。小型快照before和证据见同目录；详情见docs/release-2.0.0-r3.md。

## 2026-10-25 正式版v2.0.0修订：连接、在线更新、图标、陪伴与记忆

- 修复魔搭版本文件误命名404（兼容既有文件并后备GitHub）、系统代理识别但未实际使用、首次无可信清单导致分卷无法检测。源码及最终冻结程序真实读到魔搭2.0.0；没有改动魔搭云端。
- 用户在UI选魔搭/GitHub后独立验签主程序更新，下载校验、覆盖事务及自动重启沿用既有可信路径；增加完整覆盖包选项，保留语音/个人数据和来源锁。相同2.0.0修订不伪造更高版本，旧版需手动覆盖安装一次。
- 用户PNG接入所有UI/应用窗口、EXE、安装及快捷方式，原生LNK图标和AppID、两EXE全部内嵌ICO图像已核对。精细情绪/惊讶低频规则进入系统及工具描述，保留真实惊讶；默认改为日常陪伴，故事/讲题可分组完整展开。
- 可调1–500轮记忆，本机DPAPI/原子保存，重启恢复，清空入口及并发保护，坏文件/写失败诊断，8MB容量与模型上下文限制保留。源码437轮和冻结500轮均完成独立进程重启验证；没有调用付费API来冒充模型行为验收。
- 按用户最后要求只做重要回归：最终80项47.318秒通过，覆盖包构建另2项0.322秒通过；产品冻结核心/隔离原生安装、真实版本请求和原生更新器自动重启通过。早期531项有1项失败已修并定向验证，不宣称最新全量全绿。
- 版本仍2.0.0正式版，交付setup-r2避免旧字节混淆；新包及GitHub同步证据见docs/release-evidence-2.0.0-r2。上传魔搭文件及未来更高版本签名包说明见docs/main-update-publishing.md；详细根因/边界见docs/release-2.0.0-r2.md。

## 2026-10-24 v2.0.0 源码同步

- 用户追加明确要求将代码一并更新GitHub。本地开发历史与公开仓库不同，因此基于公开main创建源码提交并正常快进推送，保留本地开发分支/原工作区和stable标签，不强推、不覆盖远端历史。
- 同步当前程序、回归测试、构建脚本、正式版README和发布文档；本机诊断/交接、凭据、缓存、运行环境、大模型和超大训练材料不新上传，既有公开10份参考音频与历史公开证据保持原blob。
- 源码语法及凭据检查通过；v2.0.0发布标签随源码提交快进，Release说明同步源码链接。桌面和GitHub安装包字节及SHA256不变，不重新构建、不重跑下载测试。具体提交和远端验证记录见本机docs/release-evidence-2.0.0/source-sync-result.json。

## 2026-10-24 v2.0.0 正式版发布与旧产物清理

- 用户明确授权正式发布/清理，并追加右键管理员运行提示。版本改2.0.0、正式安装身份，安装前介绍/ZIP说明/GitHub说明均写明完整解压后右键“以管理员身份运行”。40项60.833秒相关回归、最终冻结/隔离原生安装及Qt核心自检通过；不追加下载测试。
- 已公开发布 https://github.com/maruyui-dev/TachiTalk/releases/tag/v2.0.0 ，非测试/非草稿、latest已核对；服务器资产SHA256与本地一致。上传后已将同一ZIP剪切到D:\桌面\TachiTalk-v2.0.0-setup.zip，77,491,946字节，SHA256 `7c554fac0ef09b009cdf85978020fd982693e525ae5cb9a229537d5e955b6e90`。配套sha256及可供手动魔搭上传的版本显示JSON；未代操作魔搭。
- 本轮没有源码提交/推送；远端v2.0.0标签锚定既有公开main72f55799，本地HEAD4666ea0与stable对象/提交不变；Release已披露自动源码归档与本地构建的区别。公钥、下载行为、稳定语音栈不变。
- 自动审批拦截批量永久删除（blocked by policy），改为回收站可恢复清理：旧work全部历史构建/包/备份、ACL备份、旧AppData/TachiTalk加载数据、IDE/Python缓存及本轮构建副本已移走。临时目录子项1,872项已回收、25项被其他程序占用/权限限制而保留；settings等旧加载数据已清。回收站未清空，不宣称已经释放相应磁盘空间；失败项逐项记录。
- 保留源码/.git/全部原脏工作、主程序开发环境、稳定语音模型/runtime、本地源音频10文件（哈希未变）；Inno工具迁入tools/inno。没有清私钥或宣传创作工程。详细发布/清理记录docs/release-2.0.0.md，证据docs/release-evidence-2.0.0。既往work链接已按本轮清理授权失效，docs小型验证记录保留。

## 2026-10-24 v1.3.10 RTX5070反馈接续合并（本机验证完成，目标完整链路仍待确认）

- 用户带回三份RTX50检测报告，提取16文件代码补丁并严格逐段比较；4文件git apply检查失败仅为CRLF，实际hunk内容均唯一匹配，保留本机后续内容及原脏工作区。小快照work/rtx50-merge-20261024/before，详细记录docs/rtx50-feedback-merge-20261024.md。
- 已本机复现并修复资源页恢复默认未写独立资源文件、重启读回旧映射；保存失败明确反馈。冻结数据按用户新要求放EXE旁user_data，不自动迁移/回退旧AppData，目录不可写报错退出，DPAPI保持。语音首次完整识别/缺失转完整/新安装代后开启本地GPT朗读一次，其他provider不切换，后续手动关闭保留，不伪造模型就绪。
- 补修协调器深嵌套损坏JSON启动退出、保存/标记写失败重试覆盖手动关闭，以及便携user_data/TEMP大小写排除。均先失败回归再修复；保留跨文件标记持续失败后退出仍可能重触发的限制。Inno/便携不带开发user_data且保留安装已有数据；原1.3.7/1.3.8及下载行为保持。
- **本机验证**：主定向42项、审查定向22项、最终全量519项614.999秒OK无跳过。22个独立冻结桌面进程验证实际PNG/DPAPI/两种重启路径、目录隔离、主动关闭保留、DPR100/125/150原控件四态及滚动；实际Inno安装/核心自检、10模块代码对象一致、真实文件系统失败诊断、实际冻结updater忙锁/恢复/坏备份通过。RTX4060实际协调器检测false→true时仍未就绪，44.203秒后真实TTS加载，聊天夹具合成默认播放成功、欠载0，48.344秒结束仅关闭自有服务。未调用付费API或重下6.2GB语音。用户要求不再下载测试时下载组已完成，此后无追加/重跑。
- **交付**：work/rtx50-merge-20261024/delivery/TachiTalk-v1.3.10-rtx50-feedback-test-main.zip，77,504,257字节，SHA256 `d70cb6005ec8cfbd23f3c49007db519068688c879efb9d9e08510e75e04b1146`；便携版TachiTalk-v1.3.10-rtx50-feedback-test-portable.zip，102,451,086字节，SHA256 `d9c0eb636d2b1bb9f29af1c4e529ededae541e34c58e7b26aae671837822ec6c`。配套sha256和小型源码接续包；独立1.3.10身份，未覆盖1.3.8/1.3.9产物。
- **边界**：新电脑报告RTX5070实际模型合成/Realtek播放通过，仅作为其历史证据；仍未完成目标冻结首次完整语音安装和用户真实付费ASR/LLM全链路。最初错误映射写入来源未证实。纠正旧交接：现有离线导入需要完整ZIP，不直接接受四分卷清单。未清本机AppData/用户缓存、未升级稳定语音环境/信任链、未改云端/稳定标签/HEAD，未提交/推送/正式发布。

## 2026-10-24 v1.3.8 安装事务修复测试包（已交付；RTX5070待目标确认）

- 用户反馈1.3.7安装语音退出后打不开。已发现实际D:\桌面\TachiTalk-Test-1.3.7的voice/applying事务（40328项），原更新器仍在持续写入；不能将截图弹窗认定为原安装已经失败。未关闭该进程、删除pending/备份或重装资源。
- 已修启动先pending后锁的顺序错误：安装进行中误启动恢复；竞争恢复的忙锁异常又覆盖共享install-result并弹“恢复未完成”。现在先探测锁，占用返回2并提示等待原安装，不覆盖原结果；真正遗留事务仍恢复，权限/IO不冒充忙锁。独立进程持锁和元数据权限回归均先失败再修复。小型快照work/voice-recovery-20261024/before；详细记录docs/voice-install-recovery-20261024.md。
- 原安装已自然完成：实际result ok=true、pending清除、语音v2ProPlus-cu128-runtime-1检查installed=true/missing=0，主程序PID29076由原更新器自动启动且Responding=true。没有执行手动恢复/删除事务/重装/终止用户进程。
- **最终验证**：定向21项3.916秒、全量502项514.209秒通过。实际冻结更新器验证占用退出/保留结果、释放后回滚成功、腐损备份保留诊断；冻结启动代码对象与产品一致，忙时不启动竞争恢复，遗留事务仍启动恢复。隔离原生Inno安装、产品核心Qt自检、SVG/ICO完整性通过；辅助程序未入交付。
- **交付**：D:\TachiTalk\work\voice-recovery-20261024\delivery\TachiTalk-v1.3.8-install-recovery-test-main.zip，77,486,639字节，SHA256 `5a12650cc6095697211ec3a7e75493fe0ed387091e82ffc0f8ab0509a1db38b6`，配套sha256。独立测试身份/目录；精确基线packaging/baselines/main-1.3.8-install-recovery-test-inventory.json，证据docs/release-evidence-1.3.8-install-recovery。未发布正式Release、未改云端、原脏工作区与HEAD/stable保持。新电脑复制清单及新账号交接见HANDOFF_RTX5070.md；BUG1/4和RTX5070仍需目标验证。

## 2026-10-24 v1.3.7 用户反馈修复测试包（已交付；BUG1/4及RTX5070待目标确认）

- 本轮直接在 D:\TachiTalk 排查四项 BUG、魔搭卡片标识及下载检测跳滚。开始核对分支/HEAD/stable 标签均与交接一致；原 ZIP 大小和 SHA256 匹配，无 TachiTalk/Python 运行进程；原未提交内容完整保留。小型源码快照在 work/bugfix-20261024/before。
- 检测两次跳滚已真实 Qt 复现并最小修复：禁用按钮导致焦点移到下方控件。语音临时降级覆盖用户自动朗读偏好已修，9项/50.876秒通过，包含独立进程。目标补充Qt箭头文件不存在警告后，确认 Inno Excludes:"assets"误排除嵌套界面图标目录，改为根锚定；原生安装四个SVG先RED后GREEN且保留用户图片。最终撤回自绘替代方案，原控件/QSS不变。魔搭两处卡片统一官网标识。
- **交付**：`D:\TachiTalk\work\bugfix-20261024\delivery\TachiTalk-v1.3.7-config-voice-bugfix-test-main.zip`，77,484,153字节，SHA256 `089e61c135b97eb5852593d5685ef25e08c2edb1e39ce4bc676c866d28b3d622`；配套sha256。独立1.3.7 Test AppId/安装目录/快捷方式，QA辅助exe不入交付包。桌面复制被系统PermissionError拒绝，交付项目内原包；原v1.3.6 ZIP字节/哈希保持不变。精确基线 packaging/baselines/main-1.3.7-config-voice-bugfix-test-inventory.json。
- **最终验证**：全量495项498.672秒通过（中间494项515.892秒仅属中间结果）。真实Inno安装四个SVG/ICO完整并保留同名用户图片；产品冻结核心自检通过；与产品相关冻结代码对象相同的隔离QA辅助程序10个独立进程验证真实FROZEN数据目录/DPAPI、保存/关闭/重启恢复、自定义映射及实际立绘、缺组件到模拟就绪的朗读意愿。实测DPR1.0/1.25/1.5各四态开关可见，检测开始/完成均不跳滚。ZIP CRC/成员、生产公钥与渠道配置、静默main gate及无QA模块混入通过。
- **本机语音**：原稳定RTX4060 Laptop、torch2.7.1+cu128/CUDA12.8，独立端口/运行目录，未开试听页，真实monitor启动TTS后82.594秒就绪，LLM夹具回复经真实合成和默认播放，spoken=true、32000Hz单声道、欠载0；测试87.032秒结束并仅关闭本次拥有服务。未调用付费ASR/LLM、未完整下载安装6.2GB语音，不能冒充目标GPU或国内整体验收。
- **待目标确认**：BUG1错误映射、BUG4恢复默认在源码及冻结的真实桌面/DPAPI/独立进程中均未复现，默认空mapping/实际图片、已有自定义与设置恢复已证实通过，未擅自清配置或合并根因。目标新增日志确认箭头资源遗漏，但仍无自动保存/恢复日志与非敏感映射数据。旧版已保存auto_read=false与主动关闭无法区分，本版保留，目标复测需明确核对自动朗读选项。完整分项记录 docs/release-1.3.6-bugfix-validation.md；交付说明 docs/release-1.3.7-bugfix-test.md；证据 docs/release-evidence-1.3.7-bugfix。未完成RTX5070 Laptop实机验收。
- **执行/保护**：曾发生辅助冻结重建与启动重叠造成QtCore DLL导入失败，已记录并改为独立输出、干净PATH、成功标记后再启动，后续全部成功；不是目标用户GPU新故障。全部原脏工作区条目仍在，最终HEAD和stable对象/提交不变；未提交/推送、未改云端或信任链、未覆盖日常安装/清缓存、未升级语音环境。独立只读审查无剩余代码/安装规则阻塞。

## 2026-10-24 v1.3.6 GitHub / 魔搭语音下载与独立静默检测（已交付测试包）

- **交付**：`D:\桌面\TachiTalk-v1.3.6-modelscope-voice-test-main.zip`，77,983,417字节，SHA256 `8b6b0866b9b6aa854c941bce65559b324b7dc9d4d653b5a9d03344223baf475e`；配套sha256。项目副本 `work/modelscope-20261024/delivery`，精确基线 `packaging/baselines/main-1.3.6-modelscope-test-inventory.json`。测试安装器使用独立AppId、默认目录TachiTalk-Test-1.3.6及独立快捷方式，不沿用正式版目录，不关闭用户程序。冻结有效载荷已在隔离QA目录原生安装核对；未覆盖用户日常安装。
- **Cloudflare移除**：UI卡片、状态、设置提示与切换入口已去除；默认配置v5仅GitHub/魔搭。旧v1–4配置备份到before-modelscope再迁移，清除旧首选，运行时过滤旧渠道，旧配置或内存列表不会重新启用。旧渠道下载缓存和来源记录保留，必须用户主动切换后才清理本任务。没有删除云端资源或修改Cloudflare账户、DNS、R2对象/稳定指针。
- **任务选源**：新在线任务独立获取并验签语音清单，对签名首分卷做Range GET，至多1KiB、单次最多3秒。计时从请求前到首字节，含连接和必要重定向，严格小于250ms选GitHub，其余（含250ms、异常、超时）选魔搭。UI显示状态、实测ms、最终渠道及原因；失败不显示0ms。GitHub未收到数据前可后备魔搭，开始后最多三次同源尝试，跨分卷/重启保持来源锁；普通续传不重新测速或删除缓存。用户显式手动选择优先，切源遵循停止旧任务→持久清理标志→清本任务→零开始，含重新启动尚无清单时的切源。
- **魔搭真实适配**：固定公开repo master resolve入口映射已上传的v1.3.0语音附件，不修改原始签名payload。入口解析到已实测的cdn-lfs-cn-1.modelscope.cn/prod/lfs-objects/64hex路径，只准明确主机/路径、HTTPS和默认证书验证；不开放任意外域。每次请求/续传从稳定入口解析，401/403临时地址失效再取一次入口，不持久化临时签名URL。保留生产release-1签名、大小、分卷/整包/文件SHA256，以及强ETag、If-Range和准确Content-Range保护；无需注册、不含上传令牌。
- **主程序检测的最终需求变更**：本轮最初已关闭自动/启动/手动检查并证明无网络请求；之后用户明确追加“上传魔搭文件，拉取验证后启用后台静默更新”。用户最终自行上传 `main-latest.json`，代理匿名实取473字节、与交付文件一致，SHA256 `f0d1093b26a037f75f3b3807cb6296f33040213d66cfcdfd6400d8905d2197c5`；验证后启用main_feed.ENABLED=True并重新冻结。最终默认只读魔搭固定文件（64KiB、总6秒），无GitHub版本API/代理后备、无弹窗或导航。版本元数据仅供面板展示，不授权可执行更新。主检测独立main_thread，不阻塞/解锁语音busy，不覆盖语音下载状态。关闭gate的无请求回归仍保留。没有代为上传或读取登录凭据。
- **语音与本地功能**：安装/修复直接使用voice_manifest独立入口，无需先检查主版本；本地语音、签名离线导入、旧版复用和文字立绘气泡保持可用。GPT-SoVITS v2ProPlus、PyTorch2.7.1+CUDA12.8未升级。新用户神态全部自动匹配；已有用户映射保存/重开回归通过。
- **测试**：初版全量461项515.500秒通过；最终开启魔搭静默检测后的全量483项519.266秒通过。新增/调整回归覆盖249、249.9999、250、250.0001、慢/超时/失败、独立语音验签、旧配置、断流/续传/手动切源、重启清理、主检查解耦、静默启动和无安装授权。先RED证据含配置/原更新请求、TTFB原7249ms误算、UI原Cloudflare与耦合、跨重启手动切源、主版本未展示；已修后通过。另同产品源码长主版本说明布局1项0.733秒通过（首次即通过，非RED）。独立审查无剩余阻塞；原生冻结主程序隔离安装/核心UI、首次映射、ZIP CRC、冻结PYZ入口/真gate、生产公钥/来源与源码一致、桌面和outputs哈希均通过。
- **本机真实链路**：生产魔搭语音清单完整读取并验签，原签名envelope与已有正式清单相同；SHA256SUMS与签名逐卷哈希一致，四卷均1KiB HTTP206。GitHub实际附件首字节约860ms，按规则魔搭；魔搭实际下载到555658字节暂停，重建Downloader并反转来源顺序后仍魔搭，If-Range/同强ETag HTTP206从555658续到1062100字节。只保存稳定resolve地址。临时URL过期刷新为确定性HTTP响应夹具测试，不冒充真实过期等待。真实UI匿名主feed读取及长来源/错误布局通过；截图actual-feed为真实面板，layout-regression-fixture明确为回归夹具。
- **尚未验收**：用户已确认国内能够直接拉取魔搭，但本轮上述时间/字节为执行主机结果；未执行整套约6.2GB语音完整下载、安装、GPU合成及国内最终安装验收。Windows10、RTX50与干净系统仍需目标实机验证，不能把可下载写成组件验收完成。
- **保护边界**：全部原修改和新增文件保留，无reset/clean/覆盖GitHub源码，无提交/推送/正式Release；HEAD4666ea0、stable标签对象979a8fba/提交8eb0d2b1保持。未读生产私钥、未重建信任链、未索取密码，未额外清理。证据：`docs/release-evidence-1.3.6-modelscope` 与 `work/modelscope-20261024`。

## 2026-10-24 用户授权清理旧测试工具、构建与备份（已完成）

- 用户取消跨电脑交接，并确认魔搭社区国内用户能够直接下载拉取。该反馈不等于完整语音安装验收；本轮只处理清理，不实施新窗口的下载渠道改造。
- 原清单共36项，最终核对原位置均已不存在：34个目录采用可恢复的回收站方式清理；1个旧配置备份文件 `packaging/download_sources.json.bak-20261023` 已删除；桌面 `ModelScope-003-Direct-Test.cmd` 在本轮开始前已不存在，不记为本轮删除。
- 已清理独立 `D:\ModelScopeDownloadTest-20261023` 工具目录、旧版测试包、各轮 `before` 源码副本、临时 `build/build-final/build2`、`qa/qa-final`、`release/release-final/dist` 安装/构建副本及空备份目录。范围限于清单中明确列出的旧产物，没有删除整个work目录。
- 回收站目录按原始清单合计4,742,045,867字节（约4.42GiB）；**未清空回收站，不能宣称已释放这些磁盘空间**。目录级永久删除被执行策略拦截后，改用可恢复清理方式成功完成。
- 保留主项目源码、Git历史、稳定语音环境、用户配置与下载状态、语音上传原分卷、发布基线及测试证据。最新v1.3.5测试ZIP保留在 `work/download-resilience-20261023/delivery/`，重新验SHA256 `3be3b68afb094bf4af05023f67f21b08216be8fcd36df5602cd7ac479c64873b` 通过；结束核对时桌面该包原路径已不在，桌面该ZIP不在本轮删除清单中，未重新复制。
- HEAD4666ea0和stable标签对象979a8fba/指向8eb0d2b1复核保持。7个保护文件中6个与10月23日快照哈希相同；`packaging/download_sources.json` 相较旧快照已有新修改（同时出现新增魔搭测试文件），本轮未编辑或回退该配置。没有将并行开发变化写成清理破坏，也没有声称全部源码与旧快照相同。
- 清单及核对结果：`work/cleanup-20261023/plan.json`、`results-20261024.json`、`verification-20261024.json`。本轮没有修改业务代码、安装/发布新程序、读取私钥或清理云端对象，因此没有重跑业务测试。

## 2026-10-23 v1.3.5 同源续传、准备提示与布局修复（已完成并交付测试包）

- **交付**：`D:\桌面\TachiTalk-v1.3.5-download-resilience-test-main.zip`，77,984,322字节，SHA256 `3be3b68afb094bf4af05023f67f21b08216be8fcd36df5602cd7ac479c64873b`；配套sha256，项目副本work/download-resilience-20261023/delivery。测试下载：https://download.jieyiblog.me/testing/v1.3.5/TachiTalk-v1.3.5-download-resilience-test-main.zip。桌面与Cloudflare完整回下载SHA一致，ZIP CRC/成员通过。
- **用户反馈**：国内Cloudflare可开始下载约1.8MiB/s，4%后自动切源，另有切源撑宽UI和首次0%疑虑；用户没有反馈完整语音安装成功。未取得该次异常日志，不能把它直接断定为超时。未停止/替换最初发现的日常PID36412或清理其缓存，稳定环境未改。
- **下载**：默认临时网络错误最多3次同源尝试。收到数据后固定来源，跨分卷/重启保存，失败保留缓存供继续/手动切源，不因慢速擅自切源。首次完全无进度且来源不可用仍可后备。签名、强ETag/Range、分卷/整包SHA均保留。手动切源清理本任务及来源记录，暂停/取消保留。
- **兼容**：旧部分/完整.part恢复来源，完整分卷快路径不丢来源身份；签名附件URL变更时仅在供应商路由唯一可确认时恢复身份，新URL从零读取，不复用不同URL字节，也不请求旧缓存URL。多候选/禁用源时保留缓存并要求明确切源。
- **界面**：真实Qt复现长错误URL撑到24830/49969px（视口1088），已修复动态标签最小宽度。按钮下方首次准备预计约5分钟提示+真实阶段/已用时间；准备中显示不确定进度，真实数据后显示百分比（不足1%显示<1%），没有人工固定延迟或到点保证。
- **验证**：最终全量425项429.607秒通过。原5项RED→GREEN13.054秒；边界3项GREEN7.773秒。两轮全量曾分别因HTTP UI等待fixture时序失败，记录full-tests.log/full-tests-final.log保留；最终修正链式worker等待和QTest.qWait的Python线程饥饿，5秒上限与断言不变/新增busy断言，8次实际HTTP从39.429秒降至4.593秒且全过。产品/冻结安装包未为绕过测试而修改。
- **真实链路**：生产语音验签；约1MiB有界Cloudflare读取，重建任务并反转来源顺序仍CF，HTTP200→206从540672字节续传，来源锁/ETag/Range通过。不是完整语音下载/安装、国内带宽提升或RTX50实机验收。
- **构建**：最终冻结/隔离原生安装、文字立绘气泡、首开全映射自动通过，公钥/来源与源码匹配，无整套语音/开发者JSON/Cloudflare凭据。PYZ含pin/wait_retry、来源锁与准备提示。精确基线packaging/baselines/main-1.3.5-download-resilience-test-inventory.json；证据docs/release-evidence-1.3.5-download-resilience。
- **边界/后续**：未公开GitHub Release，R2稳定指针仍1.3.0，仅testing新对象；未提交/推送，HEAD4666ea0与stable对象979a8fba/提交8eb0d2b1保持。若旧任务已切走，用户可手动选择Cloudflare清理旧任务后实测本版；保持现有下载状态继续重试时按原来源保留，不擅自删除。

## 2026-10-23 v1.3.4 Cloudflare 默认分发与静默更新（已完成并交付测试包）

- **交付**：`D:/桌面/TachiTalk-v1.3.4-cloudflare-test-main.zip`，77,986,366字节，SHA256 `70bd93f549074afeb2c1b23662df4609a9319a43749937d169adcb73634116b1`；配套sha256文件，项目副本work/cloudflare-defaults-20261023/delivery。Cloudflare测试下载：`https://download.jieyiblog.me/testing/v1.3.4/TachiTalk-v1.3.4-cloudflare-test-main.zip`，实际完整回下载验哈希通过，桌面哈希一致。
- **实现**：Cloudflare 默认渠道与配置v4备份迁移；新旧用户不再被旧单源偏好锁住；签名/下载/版本接口均可通过现有R2直连域。安装预检检查实际渠道，手动检测额外显示GitHub；不把GitHub失败当作Cloudflare失败。取消/失败清除“检测中”状态。
- **启动/弹窗**：线程静默检查，不强制切到下载页；上次退出在下载页则回到角色控制，明确installer语音入口保留。仅更高版本提醒，支持没有适用增量包时下载完整主程序ZIP并手动安装，普通元数据不进入无签名补丁执行器。真实Qt弹窗及ImageGen设计图在证据目录，v1.3.5仅为明示设计示例。
- **首次配置**：新用户全部映射自动，保留已保存映射；源码状态不再读取resources中的本机“平常→调皮”开发配置，原文件未改。最终冻结隔离首开实际验证全部自动；新默认公共备用代理启用，但Cloudflare无需代理。稳定torch2.7.1+cu128含sm_120，设备auto保留，本机RTX4060，不冒充RTX50实机验收。
- **线上**：旧dl Worker固定语音可读而API/latest400、main404；改用download.jieyiblog.me，不改Worker/DNS。原正式1.3.0主程序ZIP已上传并Cloudflare完整下载验原SHA；只启用Cloudflare的版本/语音生产验签、206范围、metadata no-store通过。线上最新稳定指针仍1.3.0，测试对象独立，不改GitHub Release。
- **验证**：全量413项417.069秒通过；此后检测状态/静态文案小调整，最终相关67项30.679秒通过。最终冻结/隔离安装、文字立绘气泡、ZIP CRC/成员/公钥/来源/映射排除/PYZ与桌面SHA通过。未声称最后调整后重新全量，也没有完整语音安装或用户无代理/RTX50实机验收。
- **记录**：docs/release-1.3.4-cloudflare-test.md，docs/cloudflare-downloads.md；证据docs/release-evidence-1.3.4-cloudflare，精确基线packaging/baselines/main-1.3.4-cloudflare-test-inventory.json。全工作区原修改保留，HEAD4666ea0与stable对象979a8fba/指向8eb0d2b1复核未变，无提交/推送；未读生产私钥或更换稳定语音环境。
- **后续**：用户测试本包实际语音下载/安装及RTX50合成。未来正式发布必须先镜像附件，再更新R2 latest清单和metadata/latest.json；仅更新GitHub不会自动变更R2版本指针。

## 2026-10-23 Cloudflare 语音上传材料（原分卷恢复校验已完成）

- 用户准备自行上传语音资源到Cloudflare，要求现成文件位置/文件名；若本地没有则提供。已检查项目发布/备份目录、用户下载缓存和常见下载位置：保留签名清单，但未找到完整四个发布分卷；稳定解压环境不是可直接供现有UI安装的发布包。
- 已从公开v1.3.0正式附件恢复并校验**原始分卷**到 `work/cloudflare-voice-upload-20261023/v1.3.0`，只下载一份压缩包分卷，不复制或改动稳定GPT-SoVITS环境、不重新压缩/签名。脚本 `restore_voice.py`，日志 `restore.log`；使用既有受限Downloader，部分文件/同源强ETag支持重试续传。四分卷总6,219,221,474字节，manifest7,586,508字节。
- 签名清单生产验签及对照原发布SHA已通过；四分卷和合并流哈希已完成校验，verification.json 的 ready=true，目录可供上传。完成后会生成SHA256SUMS和 `verification.json` 的ready=true；不创建额外合并ZIP。
- 原材料准备阶段仅处理本地文件；之后DeepSeek部署及本轮Cloudflare业务接入见上节。原签名清单URL未改。

## 2026-10-23 v1.3.3 代理状态图标（已完成并交付测试包）

- **交付**：`D:/桌面/TachiTalk-v1.3.3-proxy-status-icons-test-main.zip`，77,972,507字节，SHA256 `a9d43f8faa874cb4d5caf0921b9805d2085a92f50b74105e8fdb1902d12b601a`，配套 `.sha256.txt`。项目副本在 `work/proxy-status-icons-20261023/delivery`，精确基线 `packaging/baselines/main-1.3.3-proxy-status-icons-test-inventory.json`。
- **验证**：最终相关44项24.097秒通过，真实Qt三状态截图检查、隔离原生安装/核心功能、ZIP/桌面哈希及冻结PYZ中的新图标函数/三态颜色验证通过。没有为本次显示小改动重新运行全量，1.3.2的391项结果仍仅属于该版；证据 `docs/release-evidence-1.3.3-proxy-icons`。

- 用户追加要求：发现代理和未发现代理的图标明显区分。已改为绿色盾牌勾/灰色盾牌横线/橙色盾牌问号，文字同时用对应浅色底和强调色；无障碍名称与提示同步。
- 修改仅限网络卡片显示及检测中/取消/异常时状态复位，代理识别和网络下载业务未变。重新检测清除旧绿色状态；无法确认不等于未发现。
- `work/proxy-status-icons-20261023/before` 保留修改前源码；新增图像差异/文字/颜色/无障碍及重测状态回归先RED，首轮44项23.958秒通过。真实Qt三状态对比 `proxy-states.png` 是界面测试示例，不是实际网络检测结果。
- 独立只读复审未发现阻塞问题。为避免不同二进制混用既有基线，测试版本升至1.3.3，已完成冻结构建和独立安装验证。项目内旧1.3.2 ZIP原哈希仍匹配；桌面旧包本次核对已不在原路径，未由本轮删除或覆盖。未更改用户安装/代理/缓存或Cloudflare业务，未提交/推送/公开发布。

## 2026-10-23 v1.3.2 GitHub 检测与切源验证版（已交付，等待用户实测）

- **最终交付**：`D:/桌面/TachiTalk-v1.3.2-download-diagnostics-test-main.zip`，77,972,067字节，SHA256 `f1c52c9328c46d63dff2bda2469c89d1cbe37413a17cacdd654cf2cc8f480c17`；桌面配套 `.sha256.txt`，项目内同字节包在 `work/github-diagnostics-ui-20261023/delivery/`。全部解压后运行 setup，EXE/BIN需同目录，建议新测试目录。
- **最终验证**：完整391项通过410.807秒；最终冻结主程序与交付安装器相同字节，隔离原生安装/核心检查通过，首次映射全部自动、检测卡片可用、Cloudflare暂未接入。ZIP CRC/成员/桌面哈希通过，生产公钥与下载源一致；直接读取冻结PYZ确认诊断模块及最终多任务 `restart_archives` 已打入。证据在 `docs/release-evidence-1.3.2-network-test`，说明见 `docs/release-1.3.2-download-diagnostics-test.md`，精确主程序基线 `packaging/baselines/main-1.3.2-download-diagnostics-test-inventory.json`。

- 用户选择第二版资源面板、第一版网络失败弹窗；授权 GitHub / 代理检测和安装前业务逻辑，明确暂不接入 Cloudflare。后续追加：首次启动全部神态自动匹配；手动切换来源时清理当前任务缓存并从0重下；完成后再交付测试主程序。
- 保留此前全部未提交修改；小型源码备份及本轮证据在 `work/github-diagnostics-ui-20261023`。开始时发现用户 TachiTalk PID29268；未主动停止/替换该程序、清理用户实际缓存或切换其网络。原生QA在独立目录与隔离用户数据运行，明确禁止安装器关闭/重启其他应用；后续只读核对已未发现TachiTalk进程，不推断其退出原因。
- 新增 `app/updates/diagnostics.py` 和 `app/ui/update_network.py`：清单/签名清单首分卷分别作小范围 GET，单项网络等待至多8秒，并行执行；首分卷 URL 先验签，原信任重定向策略保留。只读报告系统/环境/PAC代理设置，不能据此判断全部代理或实际连接路由。Cloudflare 显示暂未接入，按钮禁用，没有对应请求或下载业务。
- 安装前检测，失败可查看详情、重测、取消或明确仍尝试现有下载源；检查与下载均在工作线程。手动检测不启动安装，关闭/取消阻止后续下载。切源先停旧任务，再清理单个签名 archive 缓存；其他任务、已安装语音不动。新增持久化 `restart_archives` 列表，清理失败及重启不能绕过待执行的清理；不同任务分别记录、按请求组件清理，安装确认保留；暂停/取消保留缓存。
- 神态映射原代码默认就是空覆盖表（所有下拉自动匹配）；已增加冷启动全行与保存后重开回归，不通过覆盖已有用户设置来实现。冻结包仍排除个人资源JSON。
- 流程、首次无缓存URL策略与取消清理等均有实际 RED 记录及修复。受影响65项79.513秒通过；追加保护后41项22.395秒通过，再补交错任务后43项23.772秒通过。中途全量387项412.762秒通过，最终以391项410.807秒及最终冻结验收为准；这些与小流量探测均不代表完整语音安装成功。
- 真实只读线上探测：清单672ms、首分卷593ms，均 HTTP206、应用各读取1024字节。检测到系统/环境代理设置，因此**不是免代理完整下载验收**。截图 `ui-1440/1200/1080.png`，失败弹窗 `network-dialog-*-fixture.png` 是明确的本地失败夹具，自动映射截图使用隔离首次数据。
- 独立审查发现的两个P2（首次无缓存固定latest清单被过严资产策略拒绝、扫描期间取消仍删除）均补先失败回归后修复。另补清理失败重试与跨重启回归。
- 用户已有阿里云个人备案域名，可规划独立下载子域名；原网站可保留阿里云。标准R2自定义域名需要同账号Cloudflare zone，届时配置DNS并保留原站记录；备案不会自动带来Cloudflare大陆网络。当前没有改域名/DNS、购买服务或上传资源。
- 构建数字版本提升1.3.2，避免与此前1.3.1不同二进制混用基线；未公开发布、提交或推送。HEAD4666ea0和稳定标签对象979a8fba/提交8eb0d2b1复核未变。稳定GPT-SoVITS/PyTorch/CUDA未修改，未读取生产私钥或索取密码。
- 下一步用户运行本轮新测试包验证检测、切源从零下载及完整安装。Cloudflare业务尚未授权实施，不能将本轮交付写为免代理分发已解决。

## 2026-10-23 分发目标澄清与网上调研（免代理渠道尚未实施）

- 用户明确要求普通用户不配置外部代理也能下载，并要求搜索其他个人开发者的做法。此前“开启代理后可下载”仅证明该条件下连接可用，不满足产品的免代理分发目标。
- 已核对 GPT-SoVITS 官方 ModelScope 整合包直链、Dub Genius 作者的网盘整合包、Cherry Studio 官方夸克入口及思源独立下载域名/网盘；调研见 `docs/download-distribution-research-20261023.md`，包含一手来源、成本及接入/验收边界。
- 建议先评估国内 ModelScope 托管，条件不满足时使用国内区域 COS/OSS（按需CDN）；版本/签名清单与分卷应同时有国内渠道，保留原签名/哈希和受限镜像映射。没有确认平台配额或“永久免费”，也没有声称任何候选已通过用户关闭代理后的完整下载验收。
- 本轮仅搜索与记录，没有修改产品/测试代码、上传资源、购买服务、改用户代理或干扰当前下载。下一步需选定并验证真实国内分发渠道，不能把新增公共 GitHub 代理或单次小流量连接写成免代理分发已完成。

## 2026-10-23 用户实际拉取反馈（外部代理开启后可以下载）

- 用户起初报告三个来源长时间0%，随后明确补充：**不开外部代理时失败，开启外部代理后可以下载**。最新截图具体错误为所选 GHFast 首分卷 ConnectionTimeoutError（连接超时）；不能将该图扩大为所有来源、所有网络条件都不可用。
- 当前已确认用户反馈的“外部代理下可下载”，尚未收到完整下载、安装及实际语音合成完成的结果；没有将开始下载记为完整安装成功。
- 本次只读核对实际Git状态、进程、日志和缓存；没有修改产品/测试代码、下载配置、安装程序或已安装程序，没有停止用户任务、切源或清缓存。缓存只读检查未取得可核实的文件增长记录，因此不虚构已下载字节数。
- 准备阶段空间检查曾作为假设排查；小样本1/8/32文件空间估算分别约0.015/0.016/0.109秒，完整清单探测没有得到完成结果，**不能据此认定空间检查是本次连接超时原因**。诊断材料在work/prepare-stall-131；没有按该未证实假设实施修复。恢复核对时未发现仍运行的这两个诊断脚本。
- 让用户当前下载继续，等待其完整下载/安装反馈；不启动额外大文件探测、构建或安装操作干扰本次实测。

## 2026-10-23 UI 与检查误报修复（已完成本地交付，等待用户完整下载实测）

- **当前交付**：`D:/桌面/TachiTalk-v1.3.1-resource-ui-test-main.zip`，77,954,899字节，SHA256 `7bfe99bfd28a95237d6e5420b54a72fc9587051b4a3b71ac17776d7e67846546`；配套 `.sha256.txt`。项目内同字节备份在 `work/ui-resource-fix-20261023/delivery/`。全部解压后运行 setup，EXE/BIN需同目录；建议新目录验证。
- **范围已完成**：资源页嵌入主面板、真实容量圆环/下载进度、速度/ETA/来源/暂停取消/续传提示、安装位置与下载设置、独立主程序/语音状态、已审核的新版本弹窗与实际后台逻辑。最新/不支持基线/接口未知/真实网络或签名失败分开处理；API失败仍保留签名附件回退。
- **最终验证**：366项全量385.994秒通过；最后一处“关闭当前所选代理后回到可用来源”配置修复后，相关30项9.741秒通过。实际线上voice生产签名与HTTP200/206约2MiB续传通过，原生冻结主程序隔离安装/核心检查通过，ZIP及桌面副本哈希通过。不是完整语音下载/安装验收；未声称最终367项全量运行。
- **持久化资料**：`docs/release-1.3.1-resource-ui-test.md`，证据 `docs/release-evidence-1.3.1-ui-test/`，精确验证包主程序基线 `packaging/baselines/main-1.3.1-resource-ui-test-inventory.json`。本次基线不能与未来不同内容的同数字版本混用。
- **保护边界**：未提交/推送/公开发布，未改安装中的日常程序及稳定语音环境；HEAD仍4666ea0，稳定标签对象979a8fba、指向8eb0d2b1未变。桌面旧1.3.0 ZIP在本次交付核对时已不在原路径，未由本轮修改/删除；没有把无法再验的旧文件写成再次验哈希成功。
- **桌面写入记录**：Python直接创建桌面文件被系统拒绝；未改ACL/策略或提权。先在项目内生成并验证ZIP，再使用PowerShell原生Copy-Item复制到桌面，新文件名不覆盖已有内容，桌面SHA实测一致。生产私钥和密码从未读取/索取。
- 下一步由用户运行新主程序，反馈实际GitHub语音拉取/完整安装结果；不自动开始完整下载、覆盖正式Release或替换用户日常安装。以下保留本轮实施过程。

- 用户明确授权实施 UI 与逻辑修复，并构建一个主程序供其验证 GitHub 资源拉取。随后确认尚未开始语音安装；本轮先前暂停已被本次授权解除。
- 已重新核对分支、未提交修改、HEAD 与稳定标签，均与交接一致；未发现运行中的 TachiTalk/安装器/独立更新器。既有修改保留，拟修改文件已做小型源码备份到 work/ui-resource-fix-20261023/before，未复制语音环境。
- 实施/验收清单：docs/resource-ui-fix-plan.md。先写复现当前版主清单 404 的测试，再修复、嵌入资源页、验证与构建。完成前不记为已修复；不替换已安装程序、不覆盖公开附件或稳定标签。
- 新增9项版本发现回归已实际 RED（原逻辑请求不存在的 main 清单、未检查基线），修复后与原 UI 测试合计19项通过6.872秒。资源页及状态分离的5项行为回归先 RED，修复及夹具隔离本机语音状态后24项通过7.734秒。证据在 work/ui-resource-fix-20261023。
- 当前已将资源页嵌入主面板，增加磁盘圆环、下载速度/ETA/来源选择、固定新增资源目录和独立旧版复用入口。用户追加要求设计更新弹窗，已使用 ImageGen 输出效果图，随后明确通过并要求实现；已将弹窗接入现有 UpdatePrompt 和后台下载流程。
- 本次测试包使用数字版本1.3.1及“资源面板验证版”标记，以免修改过的二进制继续冒充精确1.3.0基线。公开Release仍是1.3.0，本次尚未发布。测试夹具使用实际VERSION派生下一版，保留“比当前版本更新”的原测试含义。后续仍需全部回归、Qt截图、线上签名/下载与冻结构建验收。
- 第一轮全回归361项通过391.464秒；独立代码审查随后发现3个新增流程边界：切源中暂停/取消仍重试、旧主程序缓存绕过新检查状态、资源页退出时会话保存被页面白名单拒绝。另发现高级JSON禁用代理可能被界面复选框误重启；这些与导航状态问题均先补真实RED测试，再修复。修复后更新/会话专项35项通过48.597秒，需再跑最终全回归。
- 实际线上检查：公开版1.3.0、main状态current、errors为空、voice生产签名验签成功；真实Downloader首分卷读取1,078,478字节后暂停，再以HTTP206续传到2,139,534字节，ETag一致、Content-Range起点正确。没有完整下载/安装语音；证据live-check.json、github-download-probe.json、network-probe.log。
- 本机无编译器残留，已从官方GitHub获取 Inno Setup 6.7.3，经Authenticode有效签名验证后以官方 /PORTABLE=1 模式解包到本任务work目录；未全局安装或更改语音依赖。

更新时间：2026-10-23。目标版本：**v1.3.0**。

## 当前最终状态（2026-10-23：GitHub发布、桌面交付与授权清理完成）

- **正式发布**：[v1.3.0](https://github.com/maruyui-dev/TachiTalk/releases/tag/v1.3.0)，release ID421364787。公开main与v1.3.0标签实际指向72f55799ecd7fd4e5a67f2236b1c0f17246bad32；12附件均uploaded，服务器size/SHA256与最终本地清单一致。没有覆盖旧Release或稳定标签。
- **桌面主程序安装包**：`D:/桌面/TachiTalk-v1.3.0-main.zip`，77,939,279字节（约77.94MB/74.33MiB），SHA256 `d8c45415b858034f8bb31e2df7cd1a003e8f2a6d2c040a69078ed6218e4a7421`。清理后再验ZIP CRC和3个成员通过；完整解压后运行TachiTalk_main_setup.exe，EXE/BIN同目录。
- **真实测试**：原项目全量347项通过403.650秒；公开源码隔离副本全量347项通过364.268秒。实际GitHub匿名附件下载SHA、生产Ed25519验签通过；真实Downloader首次HTTP200下载后暂停，再两次206续传，Content-Range/ETag/长度均验证。仅约3.2MB探测，没有再下载完整2GB/重复安装。首次匿名API403限流，原命令重跑匿名成功，最终收据anonymous_metadata_verified=true；没有伪称首次即成功。
- **最终清理实际完成**：会话74353退出0；56目标全部删除，remaining_rows=0。dist/build/scratch/work、重复稳定备份、旧桌面安装包/备份与指定构建缓存/截图已删除。磁盘实测净回收110,147,751,936字节（102.58GiB），清理结束D盘可用287,776,796,672字节（268.01GiB）。这是本轮最终清理数字，不与此前两套QA清理数字混淆或简单相加。
- **清理报告**：`D:/桌面/TachiTalk-上传与清理结果.txt`；`D:/桌面/TachiTalk-清理未完成明细.csv`（只有表头，无失败文件）。完整逐根结果/计划/日志保存在docs/release-evidence-1.3.0/cleanup-result.json、cleanup-roots.json、cleanup-plan.json、cleanup-execution.log。历史暂存删除拒绝已由本次授权清理解决，无对应残留；未改变ACL/系统执行策略或提权。
- **保留并核验存在**：Python项目全部源码/未提交修改、.git/.venv、现用services及用户assets/resources；D:/GPT-SoVITS-v2pro-20250604；生产密钥D:/TachiTalkSigning（从未读私钥）；用户指定的D:/TachiTalk-Promo、D:/TachiTalk-PV、D:/TachiTalk-acl-recovery。没有升级torch/CUDA/GPT-SoVITS。
- **Git**：本地feature/modular-updates，HEAD仍4666ea0e1b3f255e4ee6276294e7582781f42414；任务源码仍保留为未提交修改/新增文件。临时公开worktree已正常移除，git worktree list仅原项目。stable-2026-10-22对象979a8fba7a18acaae7c579ed7795ddf75a08d9de、peeled8eb0d2b145ea065ba23f8035abb94ac0c9036956完全未变；差异空白检查通过。公开历史与本地完整历史不同，不能强推本地历史覆盖公开main。公开提交72f5579已是发布检查点；如后续整理本地检查点，先审核差异，不reset/clean或擅动稳定标签。
- **可恢复证据**：公开验收github-public-verification.json；最终交付final-delivery-verification.json（包含实际Git状态）；public-source-full-tests.txt；正式冻结core-smoke/signature/native-updater证据；原生GPU/安装/卸载/回滚/旧目录复用JSON已归档到docs/release-evidence-1.3.0子目录。工作目录已按用户要求删除，历史小节中的work路径仅为当时位置，不能再当作现存文件。
- **未来发布**：保留packaging/baselines/main-1.3.0-inventory.json及voice inventory。完整正式构建/分卷可从已验证Release取回，不需长期占用本地副本，不重新生成生产密钥。下一版main按精确1.3.0基线生成/签名文件差异包；latest附受支持main-from-*.json及当前voice-manifest。无尚未完成的上传/下载/解压/安装/清理操作。
- **验证边界**：Windows10、RTX50、干净系统、公共代理实际大文件速度/Range可用性、真实断电/磁盘故障、本次正式完整离线包再次实际安装未覆盖。先前QA完整离线及独立语音真实GPU链通过，不冒充这些未做的验收。未来功能升级仍需对应测试；本版没有启动健康检查失败后自动回滚协议，仅文件事务失败恢复。
- 当前用户的上传/桌面交付/清理要求已完成。恢复时先读本节、实际Git与证据，再执行新的明确任务；不要重新生成/上传/清理已完成内容。下方为历史阶段记录。
## 2026-10-23 恢复：上传完成，准备公开发布

- 已重新检查实际工作区、分支、最近提交、worktree、上传账本与测试进程。公开源码完整回归已结束：347项通过，364.268秒；日志已复制到 `docs/release-evidence-1.3.0/public-source-full-tests.txt`。
- GitHub草稿421364787现有12附件，全部state=uploaded，服务器size/SHA256与最终附件清单一致。公开main为72f55799ecd7fd4e5a67f2236b1c0f17246bad32；v1.3.0标签尚不存在。没有重复上传大包。
- 下一步按既有用户授权发布草稿，然后匿名验证公开API、签名清单与实际HTTP续传。公开验收通过后才删除正式附件本地副本；保留用户明确指定的三个其他项目、Python源码/.git/.venv、原GPT环境与生产密钥。
## 2026-10-23 上传GitHub、桌面安装包与最终清理（用户已授权，进行中）

- 最新授权：上传正式1.3.0到GitHub；桌面留一份主程序安装包；保留Python项目和原本本地GPT-SoVITS，清理代理生成的TachiTalk副本/构建产物；删除失败必须提供具体到文件名的完整路径清单。
- 已只读核实GitHub现有凭据有效且对 `maruyui-dev/TachiTalk` 有push权限；没有打印/保存Token。正式v1.3.0不存在，当前只有v0.2.0。创建新版草稿并上传，旧发布/稳定标签不覆盖。
- 桌面真实路径 `D:/桌面`，已复制 `TachiTalk-v1.3.0-main.zip` 并核对原SHA。随后发现README仍有0.2旧便携启动步骤，已修正文档，并只重新编译受影响的main/full安装器（不重压/重签语音）；完成后须更新桌面ZIP和附件哈希。
- 全量发布回归exec20121，日志 `work/full-tests-before-github-publish-20261023.txt`。README安装器重新编译exec49614，日志 `work/production-main-readme-rebuild.log` 与 `work/production-offline-readme-rebuild.log`。
- 公开源历史与本地完整历史没有共同祖先，差异仅为公开历史剔除的119MB超分ZIP/训练清单。不得把本地完整历史强推远端。使用基于公开main的隔离checkout，只复制本次源码改动，提交到新的公开分支，再将1.3.0 release指向该提交；不改原工作分支/HEAD/稳定标签。
- 已启动 `work/github-release-transfer.py --phase upload --voice-only`，exec56587，日志 `work/github-voice-upload.log`；持久化远端草稿ID与逐附件状态在 `docs/release-evidence-1.3.0/github-upload-state.json`。该文件不含凭据，只含公开附件ID/hash。上传API按SHA验证，未验证完不得删本地正式附件。
- 上传完成/公开校验前不执行最终清理。清理前把main/voice基线inventory和必要测试证据归入Python项目，保留生产密钥、原始services/独立GPT、用户配置与.git/.venv。dist/build/scratch/work、旧桌面包/备份等派生产物按明确目标检查后删除；未知归属/被拒路径写逐文件CSV清单，不把失败写成成功。
- 下一步：等正式安装器重编译完成→更新ZIP/桌面副本/附件账目→分组上传并验证→公开源提交与发布→下载/签名/Range线上实检→完成清理与详细失败清单。任何中断先查实际进程和本节账目，不盲重传或删尚未上传文件。
- 最新进展：347项全量回归403.650秒通过（exec20121退出0）；README安装器重编译exec49614退出0；同冻结客户端隔离安装/正常启动关闭再验通过（`work/production-release-final-readme-smoke.log`）。公开checkout发现签名测试依赖预存在work目录，已让夹具自行创建；该setup问题有真实诊断，修复后公开checkout的12项签名测试0.118秒通过，证据保存在 `docs/release-evidence-1.3.0/public-clone-tests.txt`。
- 正式附件已更新：主程序ZIP **77,939,279字节**，SHA256 `d8c45415b858034f8bb31e2df7cd1a003e8f2a6d2c040a69078ed6218e4a7421`；已覆盖本任务自己创建的桌面旧副本并再校验一致。完整包第3bin变为847,678,028字节；语音分卷/签名完全未变。总附件10,952,426,412字节（未计校验表）。
- 公开源码已在基于远端79dcf85的隔离worktree提交 **72f55799ecd7fd4e5a67f2236b1c0f17246bad32**，56个变更文件。已正常fast-forward推送main（未强推），本地原工作分支/HEAD/稳定标签不变。119MB本地资源与本地完整历史没有上传。
- GitHub草稿ID **421364787**。语音上传exec56587，非语音上传exec58086，各用独立进度账本避免跨进程写冲突；日志 `work/github-voice-upload.log`、`work/github-installer-upload.log`，账本 `docs/release-evidence-1.3.0/github-upload-state.json` 和 `github-nonvoice-upload-state.json`（忽略不公开）。仅当服务器state=uploaded、size及digest全匹配时标记verified。
- 项目中已保留 `packaging/baselines/main-1.3.0-inventory.json` 和voice inventory；小型测试/签名证据已归档到docs，不依赖后面将删除的work目录。
- 用户已明确选择 **保留** `D:/TachiTalk-Promo`、`D:/TachiTalk-PV`、`D:/TachiTalk-acl-recovery`，不得纳入清理。原独立 `D:/GPT-SoVITS-v2pro-20250604`、项目现用services/runtime、用户settings/resources、.git/.venv和生产签名密钥保留。

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

## 历史阶段结论（以顶部恢复检查点为准）

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

## 2026-10-23 正式发布及公开验收完成，开始最终清理

- 正式发布：https://github.com/maruyui-dev/TachiTalk/releases/tag/v1.3.0；release ID421364787；v1.3.0标签实际指向公开源码72f55799ecd7fd4e5a67f2236b1c0f17246bad32。12附件的服务器大小和SHA全部匹配。未覆盖v0.2.0/稳定标签。
- 首次匿名API请求曾403限流；稍后原命令重跑匿名API成功，未调用凭据回退，最终收据anonymous_metadata_verified=true。官方SHA256SUMS与voice-manifest匿名下载SHA一致，生产Ed25519验签通过，40,327文件。
- 实际官方大分卷：第一次HTTP200下载1,064,243字节后暂停；随后两次均HTTP206且Content-Range/ETag/长度正确，分别续至2,124,083/3,200,307字节，实际Downloader._transfer执行。未再次下载完整2GB或重复安装语音。证据github-public-verification.json/public-network-verification.log。
- 公开源码347项通过364.268秒；既有原生安装/推理/卸载/回滚/旧目录复用的JSON证据已归档至docs/release-evidence-1.3.0子目录，不依赖待删除work。
- 下一步移除干净的临时公开Git worktree，然后执行预检过的56项本地生成物清理；桌面ZIP已再次SHA核对。清理后实际剩余文件逐项列到桌面CSV。保留原分支4666ea0及全部源码修改、.git/.venv、现用services/原GPT、签名密钥、三个其他项目。

## 2026-10-23 检查版本404误报修复（进行中）

- 用户截图语音清单已读取（版本及5,931.1MiB可见）；用户确认尚未点击语音安装按钮。不能将截图误报当作语音下载实际失败。
- 本轮恢复已读状态并检查分支/未提交差异/最近提交/稳定标签；仍为feature/modular-updates/4666ea0，稳定标签未变，保留此前所有源码修改。
- 已定位UpdateClient.check丢弃Release API响应，始终请求main-from-1.3.0.json；本版无同版本增量包，404被UI原样汇总成所有检查源不可用。计划先写回归证明，再区分最新版/缺少适用增量包/真实网络或验签失败；语音入口明确独立可用。
- 小型复现与测试仅使用work/hotfix-130，不重新打包或复制语音。不得改动已发布稳定标签/覆盖正式附件。当前无安装进程。

## 2026-10-23 用户要求等待安装实测（修复已暂停）

- 用户明确表示先尝试语音安装，要求暂缓修复。已停止新增修改与测试/构建/发布。
- 本轮只有只读代码检查、线上复现及本状态记录；没有改动产品代码、测试代码、桌面安装包或已安装程序，也未启动语音下载/安装。
- 真实复现日志work/hotfix-130/live-reproduction.txt：最新Release v1.3.0/12附件，未发布main-from-1.3.0.json；check返回main的4次HTTP404与已验签voice清单，截图现象已确认。尚未写修复/回归，不记为已修好。
- 下一步等待用户反馈点击“安装 / 修复语音资源”后的实际表现，再决定是否继续处理检查状态误报或新的安装问题；先核对实际下载/安装进程，避免干扰用户测试。
