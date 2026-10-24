# v1.3.2 下载连接检测验证版

本轮用户明确授权所选面板/弹窗、GitHub检测、首次自动神态与切源清缓存，并要求一个新的主程序测试包。Cloudflare暂不接入下载业务，也没有域名操作、资源上传或公开发布。

## 测试包

- 桌面：`D:/桌面/TachiTalk-v1.3.2-download-diagnostics-test-main.zip`，77,972,067字节（约77.97MB）。同目录 `.sha256.txt`。
- SHA256：`f1c52c9328c46d63dff2bda2469c89d1cbe37413a17cacdd654cf2cc8f480c17`。
- 项目同字节副本：`work/github-diagnostics-ui-20261023/delivery/`。
- 全部解压后运行 `TachiTalk_main_setup.exe`，对应 `TachiTalk_main_setup-1.bin` 必须同目录。建议新测试目录；只含主程序，语音资源仍需实际下载或复用旧版。
- 版本高于当前公开1.3.0，不出现适用主程序补丁正常；语音检查和下载独立。

## 行为

- “网络与下载源检测”显示GitHub真实资源连接、代理设置识别及Cloudflare暂未接入；检测耗时指资源前缀GET耗时，不是ICMP ping或下载速度。
- 安装 / 修复语音先取得可信语音清单，再检测官方清单和对应首分卷。清单与分卷独立显示，清单成功不能代表分卷成功。首次手动检测没有可信清单时分卷显示未检测，不从不可信元数据构造安装地址。
- 分别8秒网络总超时、每项应用最多读取1KiB；并行检测。服务器忽略Range时也只读取前缀后关闭。HTTP、超时、错误页面、长度/范围错误保留；签名与完整哈希仍由现有安装流程执行，检测不授予安装权限。
- 固定官方latest清单端点仅用于诊断发现，其余资产沿用严格官方仓库URL策略；重定向仍受原允许列表约束。
- 代理识别只读系统/环境/PAC设置，输出不含代理URL、用户名或密码；不能识别所有TUN或确认该连接实际走代理。现有下载传输策略未因识别而自动改变。
- 失败弹窗可重测、取消，或明确仍尝试现有来源；该入口避免GitHub直连失败阻断用户可用的现有备用源。Cloudflare按钮禁用并解释暂未接入，无虚构可用性。
- 手动更换来源：停止旧连接→清理当前任务签名archive缓存→进度0%重下。选择同一来源不清理；暂停/取消保留缓存；其他任务、安装文件及稳定语音环境保留。
- `restart_archives`保存待清理任务的签名archive SHA256列表；不同组件不互相覆盖。删除失败阻止新源下载，重试先重做清理；重启后prepare也检查此记录。按用户请求的具体组件清理，成功仅移除该SHA；清理拒绝目录链接/junction或异常路径。
- 首次启动所有神态下拉均自动匹配（内置/同名/平常），原有显式映射保持。此默认原本已存在，本轮增加回归和冻结冷启动验证，未强行重置用户配置。

## 模块与验证

`app/updates/diagnostics.py`负责只读网络和代理识别；`app/ui/update_network.py`负责卡片/弹窗；`UpdateControls`串联检查、探测、恢复与切源任务；`UpdateClient.reset_download/prepare`执行受限缓存清理和跨重启保护。

本轮源码备份、RED/GREEN、本地HTTP、真实Qt截图与线上小流量探测在 `work/github-diagnostics-ui-20261023/`。最终证据归档在 `docs/release-evidence-1.3.2-network-test/`。独立代码审查的首次latest URL、扫描期间取消以及交错任务清理问题均先复现后修复。

- 最终完整391项测试通过，410.807秒。此前中途387项412.762秒通过，追加边界后43项专项23.772秒通过；最终完整结果覆盖最终代码。
- 最终冻结主程序真实隔离安装通过；中文含空格目录、隔离LOCALAPPDATA、无语音核心功能、检测卡片、Cloudflare禁用状态及首次自动映射均验收。
- ZIP CRC、EXE/BIN成员SHA及桌面副本SHA通过；生产公钥/来源配置一致，无语音环境或开发者资源JSON。冻结PYZ确认包含诊断、弹窗和最终多任务待清理列表，安装的EXE与交付构建字节一致。
- 本次精确基线：`packaging/baselines/main-1.3.2-download-diagnostics-test-inventory.json`。相同数字版本的未来不同文件不能冒充该基线。
- 未主动替换用户安装、停止用户程序、清理实际下载或改变代理。未读私钥，未升级稳定语音环境；HEAD和稳定标签未变。没有提交、推送或公开发布。

线上诊断探测在当前检测到代理设置的环境中返回两项HTTP206，各应用读取1024字节；不代表关闭代理或全量下载/安装成功。失败弹窗截图用本地夹具展示恢复状态，不是线上失败证据。

## 域名结论

用户拥有阿里云个人服务器的已备案域名，可以规划下载子域名，原网站可继续保留阿里云；不必转移域名注册商或原服务器。标准R2自定义域名要求该域名zone在同一个Cloudflare账号，后续需要正确配置DNS并保留原站记录。Cloudflare大陆网络是另行服务，现有备案不会自动开通；本轮未更改DNS。

官方资料：[阿里云备案域名说明](https://help.aliyun.com/zh/icp-filing/basic-icp-service/support/for-the-record-domain-faq)、[R2公开桶与自定义域名](https://developers.cloudflare.com/r2/buckets/public-buckets/)、[Cloudflare大陆网络接入](https://developers.cloudflare.com/china-network/get-started/)。
