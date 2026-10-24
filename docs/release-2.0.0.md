# TachiTalk v2.0.0 正式版发布与清理

日期：2026-10-24。用户明确授权清理旧副本/缓存/备份、删除AppData加载数据、改为2.0.0正式版并上传GitHub，然后将安装包移到桌面。随后追加安装说明需提示右键“以管理员身份运行”。

## 正式发布

- GitHub：https://github.com/maruyui-dev/TachiTalk/releases/tag/v2.0.0 。公开、非draft、非prerelease，已核对latest指向v2.0.0。
- 最终包：D:\桌面\TachiTalk-v2.0.0-setup.zip；77,491,946字节；SHA256 `7c554fac0ef09b009cdf85978020fd982693e525ae5cb9a229537d5e955b6e90`。
- 上传GitHub确认服务器digest后才使用Move-Item移到桌面；源交付目录已无ZIP。桌面再次计算SHA256与GitHub一致。配套TachiTalk-v2.0.0-setup.sha256.txt。
- 安装包内含TachiTalk_main_setup.exe、同名-1.bin及安装与使用说明。正式AppId/默认目录/快捷方式沿用正式渠道；AppVersion2.0.0、BUILD_LABEL正式版；不是TestBuild产物。
- 安装前介绍、包内说明、GitHubRelease说明均明确：完整解压后右键点击TachiTalk_main_setup.exe，选择“以管理员身份运行”。没有对本机日常安装执行提权安装。
- 本次发布主程序安装包，不含大型语音runtime/模型；可从资源页安装或复用已有完整语音。GitHub原v1.3.0签名语音资源继续存在，公钥/下载配置与稳定torch2.7.1+cu128/CUDA12.8环境未变，不读取私钥、不重新签发清单。
- 桌面另有TachiTalk-v2.0.0-main-latest.json，供用户如需更新魔搭面板版本显示时手动上传并命名为main-latest.json；未代操作魔搭、未改云端版本文件。该文件只是显示元数据，不是安装授权。
- 初次发布时仅上传资产，标签锚定公开main72f55799；用户随后明确要求同步源码，现基于该公开提交加入当前源码并正常快进推送main，v2.0.0标签快进到对应源码提交，Release同步说明。保留本地开发HEAD4666ea0/工作区，旧stable标签未改。具体远端提交核对见本机source-sync-result.json，安装包字节不变。

## 验证

- 继承此前519项614.999秒完整回归、22个独立冻结桌面进程及本机真实TTS合成播放证据。
- 本轮正式版调整后40项60.833秒相关回归通过；覆盖安装资源、本地目录、协调器、安装事务、配置、原控件和滚动。不重新运行下载测试或下载6.2GB语音。
- 最终冻结代码内版本/正式标签正确，生产公钥/下载配置哈希一致，无tests模块、user_data或本机配置混入。
- 使用同一产品payload和同一Inno脚本分别编译正式安装器及无注册QA安装器，隔离原生安装后产品EXE/Updater字节相同、SVG/ICO完整、实际Qt核心自检通过，数据创建在该隔离目录user_data。
- 管理员提示追加后再次编译/安装核对，最终GitHub和桌面均为追加后的同一包；之前未上传的中间包随构建目录清理。
- 初次上传准备发现本地HEAD不在公开仓库，未创建任何公开产物；改用已存在公开main作标签锚点，并如实说明本地工作区未同步，之后上传/发布成功。
- RTX5070历史模型播放报告与本机证据分开；目标冻结首次完整语音安装、真实付费ASR/LLM链路仍不宣称已完成。

## 清理范围与限制

- 批量永久删除被自动审批以blocked by policy拦截，未换工具绕过永久删除限制；改用Windows回收站可恢复清理。**回收站未清空，移入回收站不等于磁盘空间已释放。** 用户可手动核对后清空回收站。
- 旧work内16轮构建/副本/测试包/备份/下载材料、ACL恢复备份、旧AppData/Local/TachiTalk、IDE缓存、Python缓存，以及本轮构建目录已移回收站。项目work现无构建副本。
- 本机AppData旧加载目录原位置已不存在；未把旧Key/session复制进工程或新包。未发现Roaming同名目录。
- 临时根目录正在使用不能整体移走，改为回收其明确子项：1,872项已移回收站，25项因其他程序占用或权限限制保留，包含Tencent缓存及若干.tmp文件。项目settings/resources/tts/updates等旧加载数据已移走；逐项结果见cleanup-cache.json，没有强制关闭进程或放宽权限。
- 保留D:\TachiTalk源代码/.git/原未提交工作、.venv开发依赖、services/gpt_sovits稳定运行环境和模型，以及assets/audio原10份文件；逐文件SHA256核对未变，AppData未发现需额外保全的源音频。
- Inno构建工具从旧work迁入tools/inno，供继续开发使用，并加入.gitignore。宣传创作工程TachiTalk-Promo/PV、Get_voice及仓库外签名材料不是安装副本，未误删或读取其私钥。
- 本轮没有关闭用户进程，未清空系统回收站；不能声称已永久释放旧产物占用。

审计证据：docs/release-evidence-2.0.0。包含最终GitHub公开元数据/桌面校验、原生安装自检、40项回归及具体清理清单。历史文档指向旧work的路径已按用户授权清理，不再保证可打开；必要小型验证证据保留在docs。
