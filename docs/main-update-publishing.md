# 主程序UI更新与魔搭发布

客户端默认静默读取魔搭固定 `main-latest.json`；固定文件不存在时兼容本次误上传的 `TachiTalk-v2.0.0-main-latest.json`，再后备官方GitHub Release版本信息。版本提示不授权执行文件操作。

发现更高版本后，用户点击“更新主程序”，选择魔搭或GitHub。客户端独立获取 `main-from-当前版本.json`，核对已有生产公钥签名、组件、目标版本及基线版本，再显示更新说明。确认后在UI下载、校验分卷和整包SHA256，独立更新器等待主程序退出，事务覆盖并自动重启。失败保留诊断及可恢复备份。源码运行不会被二进制更新覆盖。

主程序包只允许程序白名单文件；不修改user_data、用户图片/源音频、语音环境和模型。主程序来源选择不覆盖语音来源偏好；暂停/续传保留来源锁，主动切源停止旧任务后清理本任务缓存。

## 本次v2.0.0修订包

本次仍为正式版2.0.0，使用 `TachiTalk-v2.0.0-setup-r2.zip` 区分旧字节。已安装旧2.0.0的用户手动同目录覆盖安装一次；相同版本不冒充更高版本推送。此次不制作虚构的2.0.1签名包，也不读取生产私钥。

上传本次桌面交付目录内的3个文件到现有魔搭仓库master根目录：

| 文件 | 用途 |
| --- | --- |
| TachiTalk-v2.0.0-setup-r2.zip | 用户手动下载安装 |
| main-latest.json | 固定后台版本文件；必须保留这个名字，不加版本前缀 |
| SHA256SUMS-main-v2.0.0-r2.txt | 本次安装ZIP校验值；不会覆盖语音的SHA256SUMS.txt |

仓库为 `MaruYui/TachiTalk-Voice-Runtime`。不要把外层交付文件夹一并作为子目录上传。原voice-manifest、四个语音分卷及原SHA256SUMS.txt保留。不要上传work、QA程序、用户数据、密钥、未签名payload或整个项目。

## 将来发布更高版本，例如2.0.1

1. 先把代码/安装器版本改为2.0.1并构建正式主程序。在受保护的既有签名环境制作完整主程序覆盖包，例如：

   ```powershell
   Set-Location -LiteralPath D:\TachiTalk
   & .venv\Scripts\python.exe -B scripts\component_release.py --component main --version 2.0.1 --base-version 2.0.0 --full-main --client D:\TachiTalk\dist\TachiTalk --output D:\TachiTalk\work\main-2.0.1-from-2.0.0
   ```

   这沿用既有`TACHITALK_SIGNING_KEY`签名环境；不在聊天、文档或命令正文填写私钥或密码。未配置签名环境时仅生成未签名中间产物并报错，不能拿它发布。`--full-main`不需要旧版inventory，只包含主程序白名单文件。

2. 上传签名清单和对应分卷到GitHub该版本Release附件。魔搭保持以下路径：

   ```text
   main-latest.json
   main/
     v2.0.1/
       main-from-2.0.0.json
       main-2.0.1.zip.part000
       # 如有更多分卷，按签名清单追加
   ```

   签名payload仍保留官方GitHub地址，魔搭客户端按固定规则映射，不修改签名内容。

3. 将固定main-latest.json的版本、说明、发布时间更新为新正式版，并同步GitHub版本。它只包含schema=1、component=main、channel=stable、version、title、notes、published_at，不放installer/archive/parts/signature/files。
4. 如要支持多个旧版，为每个旧版提供对应签名清单。完整覆盖包应复用同一份目标归档/分卷，只改变清单基线版本并重新签名；不要把不同基线的增量包上传成同名分卷。
5. 发布前验证签名、目标/基线、两来源路径、覆盖更新与重启。仅上传普通安装ZIP，不会自动获得UI内执行安装的授权。

500轮记忆是本机保存上限，8MB额外容量保护仍生效；实际传给LLM的轮数由用户选择，受服务模型上下文容量限制。记忆使用当前Windows用户DPAPI，不作为跨账号明文迁移文件。
