# v1.3.0 模块化安装与发布维护

## 当前边界

客户端保持现有 Python 3.12 / PySide6 / PyInstaller onedir 结构。业务代码仍在约数 MB 的 EXE 内，业务变化会重发该 EXE；不为首版增量更新改写加载器。Qt DLL 等未变化文件按 SHA-256 跳过。GPT-SoVITS 的 Python 3.9.13、PyTorch 2.7.1+cu128、CUDA 12.8 不升级、不替换版本。

```text
TachiTalk/
  TachiTalk.exe                  主程序
  TachiTalkUpdater.exe           独立 onefile 更新器，运行前复制到用户缓存
  _internal/                    客户端依赖及内置发布公钥、默认下载源
  resources/control_panel/      UI / 样式
  assets/*.png, assets/bubbles/  主程序初装的立绘和气泡（增量更新不碰 assets）
  scripts/                      稳定的语音服务启动桥接脚本
  release-version.json          安装版本记录
  services/gpt_sovits/           可选语音环境、模型、推理代码
  assets/audio/tts_reference/    可选角色参考录音
  .tachitalk-transactions/       安装备份，保留供恢复，不能随意删除
%LOCALAPPDATA%/TachiTalk/
  settings/, assets/, resources/, logs/  原有用户数据
  updates/download_sources.json         用户可编辑下载源
  updates/downloads/<archive-sha256>/   分卷、.part、.state.json、合并ZIP
  updates/install-result.json           独立更新器结果
```

语音暂作为一个可靠组件独立版本化，版本名 `v2ProPlus-cu128-runtime-1`。只改模型时可利用该组件自己的基线 inventory 生成文件差异包，不会更新主程序。尚未拆成多个互相依赖的模型组件。

推理包按实际导入筛选：保留 TTS_infer_pack、AR、module、text、feature_extractor、eres2net、BigVGAN、f5_tts、必要工具模块和 AP_BWE 权重；TTS.py 在导入时引用这些模块，不能只按当前模型分支删掉。保留选定 GPT/SoVITS 权重、Hubert、Roberta、语言识别和声纹权重。排除训练入口、prepare_datasets、训练 filelists、GUI/WebUI/导出工具、缓存和日志。私有 runtime 保持已有依赖，不通过删除依赖包冒险瘦身。是否可实际推理由 QA 报告决定。

## 用户安装与迁移

1. 首次安装可用 `TachiTalk_main_setup.exe` 加同名 `.bin`，默认当前用户目录，无需管理员。全部安装数据先在本地安装，不以 GitHub 可用为前提。
2. 完整离线 `TachiTalk_setup.exe` 加 `.bin` 可选“仅主程序”或“完整离线”。安装器沿用既有 Inno Setup，删除了原先无条件删除 runtime 的规则。
3. 安装最后可勾选打开可选语音下载向导。主程序先安全装好，随后通过同一个 Qt 资源面板后台下载；失败或跳过不会回滚主程序。这是安装器向资源面板交接的方式，安装器本身不实现另一套 HTTP 下载器。
4. 已装主程序后，在侧栏“更新与语音资源”检查语音清单，确认组件版本、大小和磁盘空间，再安装 / 修复。完整验证成功后退出程序，独立更新器安装，再启动。
5. “暂停 / 取消”停止网络读取并保留进度；“重试 / 继续”重新检查响应后续传；“删除下载缓存”需要明确确认，只清理下载缓存。
6. 离线导入需要维护者签名 JSON 和完整 ZIP。大包分卷先合并为清单对应的完整 ZIP，客户端会重新验证大小、SHA-256 和签名；不会直接执行导入文件。
7. v0.2.0 首次迁移使用 v1.3.0 主程序安装器，不能指望没有更新器的旧 EXE 自我更新。选原有可写目录，主程序覆盖自身文件，保留语音和已有 assets。安装器查询旧 Inno 安装位置，并保留目录选择页；原来装在 Program Files 且无写权限时应选新的用户目录。
8. 换目录后可在资源面板选择可信旧安装目录，复用其 `services/gpt_sovits` 和参考音频，重启生效，无需复制十余 GB 环境。新安装自身 runtime 优先。不要删除仍被复用的旧目录。配置、日志和导入资源仍留在既有 LOCALAPPDATA，DPAPI 限同一 Windows 用户。
9. 托管语音卸载通过独立更新器执行，仅删除安装记录中 SHA-256 仍匹配的文件；修改过的文件和未登记文件保留。没有托管清单的旧版目录不会被自动删除。备份也会保留，不宣称卸载一定立刻释放全部空间。

## 下载源和续传

`download_sources.json` 中 `sources` 管理附件，`manifest_sources` 管理签名清单，`api_sources` 单独管理 GitHub API。更改设置无需重新编译。`priority` 越小越靠前，`enabled=false` 明确禁用。

按用户最后要求，公共代理是 `enabled=true, fallback_only=true` 的待命源：先尝试所有常规源及有限重试，再自动尝试待命源。它们不会在官方正常时接收资源请求；明确禁用后不会自动开启。默认候选 GH-Proxy / GHFast 只属于配置，不出现在业务逻辑。API 代理单独配置，不能从附件成功推断 API 可用。API 不可用时仍继续读取固定官方 Release 附件清单。代理需要更换域名时修改本地 JSON。

附件原始地址仅允许 `github.com/maruyui-dev/TachiTalk/releases/download/<tag>/<asset>`。代理前缀必须是用户本地配置的 HTTPS 地址；逐跳限制重定向到同一代理或明确允许的 GitHub 附件域名，保留 TLS 验证，不发送开发者 Token。公共代理未做大文件线上验收，不保证可用性、速度、Range 或持续服务。代理改变域名或重定向到未允许域名会安全失败。

清单源返回 HTTP 200 也必须先通过 JSON、组件类型及 Ed25519 验证才算可用；错误页面或无效签名会在有限重试后继续下一源。不会因为代理用200返回错误页而接受内容或提前停止所有后备尝试。

临时状态记录签名大小、目标 SHA-256、具体源 URL 和强 ETag。只有同一源、相同目标及强 ETag 才请求 `Range` + `If-Range`；严格验证 206 的起点、终点、总长度和 ETag。服务器返回 200 时截断重下；错误范围、416 或内容校验失败会使旧续传状态失效。没有强 ETag 时保守重下。换源不复用部分文件；已完整下载并通过 SHA-256 的分卷可以复用。文件写入、校验、合并、解压均在后台线程或独立进程执行。

## 清单与签名

签名 envelope 为 `{key_id, payload, signature}`，Ed25519 签名覆盖 `json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)` 的 ASCII 字节；signature 和公钥是 Base64。公钥通过可信安装包的 `packaging/release_keys.json` 内置。下载源、API 和代理不能提供或替换信任根。2026-10-23已接入维护者生成的生产公钥 `release-1`；必须重新冻结主程序及更新器才能进入正式安装包，既有QA测试公钥产物不可发布。公钥缺失或清单不匹配仍会拒绝安装。

payload schema 1：

```json
{
  "schema": 1,
  "component": "main",
  "version": "1.3.1",
  "base_version": "1.3.0",
  "title": "对话与气泡更新",
  "notes": "面向用户的更新说明",
  "published_at": "2026-10-22T00:00:00+00:00",
  "files": [{"path": "TachiTalk.exe", "size": 123, "sha256": "64位小写十六进制"}],
  "delete": ["明确需要删除的旧文件"],
  "archive": {"size": 123, "sha256": "完整ZIP的SHA-256"},
  "parts": [{"name": "main-1.3.1.zip.part000", "size": 123,
    "sha256": "分卷SHA-256",
    "url": "https://github.com/maruyui-dev/TachiTalk/releases/download/v1.3.1/main-1.3.1.zip.part000"}]
}
```

上述值为结构示意，不能作为有效清单安装。voice 使用独立版本名、`base_version="*"` 全组件包或精确语音基线、`min_main_version="1.3.0"`。主程序必须是精确 base_version，错误版本拒绝。主清单附件命名 `main-from-1.3.0.json`，语音清单 `voice-manifest.json`；同一个 Release 可以提供多个基础版本的主程序补丁，未发布某基线包时提示手动主程序升级，不重下语音。

ZIP 必须与签名 files 一一对应；拒绝未登记文件、符号链接、路径穿越、Windows 保留名称、大小不符或哈希不符。主程序增量文件只允许 EXE、客户端 _internal、UI、许可证、明确的桥接脚本等；不允许语音、用户配置、日志和 assets。删除操作必须显式列出且通过同一组件白名单。

## 更新与恢复

启动延后 1.2 秒后台检查版本；无新版本不弹窗，失败仅记录资源面板状态。新版本弹窗包含当前/目标版本、发布日期、标题、说明和大小。“稍后”关闭提示，原程序继续运行；不会静默升级语音组件。

确认更新后下载/复用分卷，验证每卷、完整 ZIP 和签名，再将独立 updater 复制到用户目录运行。helper 等待主程序退出，包括原有拥有的语音服务收尾；在文件锁下校验实际版本、空间和组件范围。先解压校验到临时 stage、备份全部涉及文件，再一次持久化完整操作计划，之后才替换文件或执行明确删除，最后提交版本记录。避免对数万运行库文件逐次重写不断增长的日志。失败恢复原文件；进程意外退出的未提交事务会在下次启动时通过独立 helper 恢复。主 EXE / DLL 不在仍运行时直接覆盖；占用或权限问题作为失败处理，不强制提权。等待主程序退出超时时不再启动第二份主程序；安装交接前的暂停同样阻止 helper 启动。

磁盘满、备份损坏或第三方持续占用使恢复无法完成时保留 journal / backups，并停止自动重启循环，提示人工处理。备份保留以便审计和恢复；目前没有自动清理备份策略。这里保证文件事务回滚，不将“文件替换成功”冒充“所有硬件的新版运行已通过健康检查”。

## 构建与发布

在 `.venv` 中运行，原有推理环境不安装任何新包。客户端增加 `cryptography==47.0.0`。本地没有 pip 时可使用 `uv pip install --python .venv/Scripts/python.exe -r requirements.txt`，不要对 services 下的 Python 执行此命令。

首先在安全环境生成 Ed25519 密钥，私钥放在仓库之外的安全存储，只向 `packaging/release_keys.json` 写入 `{ "release-1": "Base64原始32字节公钥" }`。私钥路径通过 `TACHITALK_SIGNING_KEY` 提供，可选密码通过 `TACHITALK_SIGNING_PASSWORD`。不得提交私钥、生产 Token 或导出的用户设置。密钥轮换需通过旧信任根签发的主程序更新加入新公钥；丢失私钥或旧版本无法验证时用可信完整安装包迁移。

公钥不需要申请、购买证书或向 GitHub 注册。它与保密私钥一起在本机生成：私钥为清单签名，客户端用公开的公钥验签。首次配置一次，后续正常发布复用；私钥或密码丢失会影响已安装客户端后续验证更新，应分别安全备份。

本项目当前已完成公钥接入：从 `D:\TachiTalkSigning\release-1\release_keys.json` 读取公开配置并合并到 `packaging/release_keys.json`，只包含 `release-1` 公钥，没有复制私钥。以下生成步骤供初次配置参考，已有这对密钥时不要重复生成。构建器会将该公钥配置同时打包到主程序和独立更新器；正式发布前需要重新冻结构建，并由维护者使用原私钥对清单签名、以此公钥验签。

在你自己电脑的 **PowerShell 交互终端** 运行（不要把密码发进聊天）。本机项目虚拟环境Python写AppData被拒，而现有独立 `D:\Python\python.exe` 已安装加密库且预检通过；以下使用这个解释器与仓库外独立目录，不修改客户端或语音环境。其他电脑需换成自身可信且已安装 `cryptography` 的Python路径。先执行无密码预检：

```powershell
Set-Location D:\TachiTalk
& D:\Python\python.exe scripts/create_signing_key.py --directory 'D:\TachiTalkSigning\release-1' --check-directory
```

看到“目录可写”后，再执行生成命令：

```powershell
& D:\Python\python.exe scripts/create_signing_key.py --directory 'D:\TachiTalkSigning\release-1'
```

脚本先创建新目标目录并实际写入、同步、删除不含密钥的探测文件，再隐藏询问并确认至少12字符的密码；`@` 等符号可以使用，输入时不会显示字符。随后创建加密 PKCS8 私钥 `release-1.pem` 和可公开的 `release_keys.json`。预检不产生密钥，退出时只尝试移除自己创建的空目标目录；密码不一致或取消时也如此处理。拒绝项目内路径，拒绝覆盖已有目录；部分写入留下的文件会保留，不能删掉重试而丢失私钥。

若提示 WinError 5，属于目录写入权限问题，与密码中的符号无关。本机已复现项目虚拟环境进程被拒、独立Python成功的差异；上述独立Python与D盘目录已实际预检成功。AppData路径解析还曾指向Codex应用的LocalCache，长期密钥应存放在独立安全目录。其他电脑仍失败时检查所用Python进程的权限/系统拦截和目标目录权限，不要反复输入密码重试。无需默认管理员运行，不应放宽整个 AppData 的权限或关闭系统防护。**只复制公钥 JSON 内容到项目的 `packaging/release_keys.json`**，私钥及其目录不得加入项目或安装包。已有多个发布公钥时合并 JSON，不能随意删掉仍被使用的旧信任根。

发布签名时，把 `TACHITALK_SIGNING_KEY` 设为该加密 PEM 的本地路径，再运行下面的签名/打包命令。本机交互终端会隐藏询问私钥密码，无需把密码写在命令行中。CI 没有交互终端时必须从受保护 Secret 设置 `TACHITALK_SIGNING_PASSWORD`，缺失会明确失败，不会一直等输入。工具本身不会替你创建正式 Release 或上传私钥。

```powershell
# 主程序安装包；会构建单独 updater。每轮使用新的 work-dir。
& .\.venv\Scripts\python.exe scripts/build_release.py --main-only --compiler '你的ISCC.exe路径'

# 完整离线安装包，使用同一个 Inno 配置，带可选 voice 组件。
& .\.venv\Scripts\python.exe scripts/build_release.py --skip-freeze --compiler '你的ISCC.exe路径' --work-dir build/offline-130

# 保存首次 1.3.0 客户端的完整文件哈希，作为下一版基线。
& .\.venv\Scripts\python.exe scripts/component_release.py --component main --version 1.3.0 --client dist/TachiTalk --inventory-only --output build/main-1.3.0-inventory.json

# 独立语音包，自动按 <2GiB 分卷。
& .\.venv\Scripts\python.exe scripts/component_release.py --component voice --version v2ProPlus-cu128-runtime-1 --tag v1.3.0 --output build/voice-130

# 下一版：先将 app/version.py 和安装器版本同步为实际目标，构建客户端后做差异。
& .\.venv\Scripts\python.exe scripts/component_release.py --component main --version 1.3.1 --base-version 1.3.0 --base-inventory build/main-1.3.0-inventory.json --client dist/TachiTalk --notes build/notes.txt --output build/main-131

# 构建机无私钥时保留 unsigned-payload.json，在安全签名环境单独签发。
& .\.venv\Scripts\python.exe scripts/sign_manifest.py --payload build/main-131/unsigned-payload.json --keys packaging/release_keys.json --key-id release-1 --output build/main-131/main-from-1.3.0.json

# 原有完整便携 ZIP / 合并脚本流程仍可使用（完整语音不进入主程序补丁）。
& .\.venv\Scripts\python.exe scripts/package_portable.py --help
```

`component_release.py` 缺私钥时生成未签名包并明确以非零退出，不能把该产物当作可发布清单。签名后将相应 JSON 和所有 `.partNNN` 上传同一 GitHub Release，完整离线 setup + bin / 便携包亦可作为备用；不要把未合并的分卷当 ZIP 导入。每个被标记为 latest 的主程序 Release 也应附上当前有效的 `voice-manifest.json`，即使语音版本未变；可原样复用其签名和指向旧语音 Release 的资源 URL，无须重复上传语音分卷。若缺少此附件，该 Release 的在线语音发现不可用，用户仍可导入旧签名清单。发布需要维护者显式操作；本任务不会推送或发布。后续采用 GitHub Actions 时将发布 Token 和签名材料放在受保护 Secrets / Environment，签名私钥不要写入工作流正文。

仅发布语音新版本时，可将语音附件放在独立、非 latest 的 Release，并由维护者显式把新签名 `voice-manifest.json` 附到当前主程序 latest Release，作为资源目录。若改用新的 latest Release，它必须同时携带仍受支持的 `main-from-<基线>.json` 与当前语音清单。客户端通过 latest 附件路径发现资源；漏附清单时会显示检查失败，不会把其他组件当作主程序更新。上述操作只更新小清单，不要求重复上传未变化的主程序或语音分卷。

QA 编译支持 `/DQAMode=1`：不写卸载注册表、不建快捷方式、不自动启动安装后业务，不查询稳定安装位置。此参数仅供临时目录测试。`tests/run_modular_release_qa.py --full` 用内存中的临时测试密钥构建 QA 客户端，验证安装、独立 updater、锁定文件回滚、完整离线推理与语音分卷；输出不可作为生产包分发。实际执行结果见 IMPLEMENTATION_STATUS.md 与交付报告。
