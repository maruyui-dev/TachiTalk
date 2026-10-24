# 语音安装期间重开误报恢复失败（2026-10-24，v1.3.8验证完成）

## 实机证据

- 用户截图为“TachiTalk 更新恢复：恢复未完成，请查看 updates/install-result.json 并保留事务备份”。实际目录 D:\桌面\TachiTalk-Test-1.3.7，主程序版本1.3.7；本轮未替换该目录的任何文件，也未关闭用户进程。
- 用户本机 %LOCALAPPDATA%/TachiTalk/updates/install-result.json 为 ok=false、RuntimeError“已有安装或更新进程正在运行”。安装目录 pending 仍为 voice/applying，40328条操作、全部 existed=false，语音 component-version.json 尚未产生。
- 真实原更新器 onefile 父PID46628/子PID31392 自13:01:33运行；两次只读I/O采样的子进程写入量13761215310→13794136381字节、写操作76076→79514，说明仍在工作。按本轮全新文件的顺序替换计划，只读二分边界观察到28462/40328，下一项为torch/include头文件。该值是当时文件序列观察，不是按字节计算的总进度或完成时间保证。
- 小型快照 work/voice-recovery-20261024/before：本轮涉及源码、状态文档、实际pending元数据（约5.2MB）、失败结果；未复制约6.2GB压缩包、整套语音环境或清理下载缓存。没有输出整份40328项清单作为结论。

## 根因与验证计划

1. bootstrap 在检查安装锁前，看到pending便启动 --recover；正常安装进行中也会有pending，因此误启动竞争恢复。
2. 恢复进程抢锁失败后，把失败覆盖到共享install-result.json，并因pending仍在而显示“恢复未完成”；这不能证明真正的原安装已失败。
3. 用户看到应用退出后没有安装进度窗口，容易以为安装已结束；本轮先修正重复启动/恢复判定和错误归属，保留原事务。

计划在临时目录独立子进程持锁，先验证旧启动会错误启动恢复及覆盖结果，再以最小修复区分忙锁/权限/IO错误。无活动安装且遗留pending时必须继续真正恢复；真实失败仍报告并保留备份，不绕过事务或伪造成功。实际原更新器保持运行，后续只读核对完成/自动重启结果。

## 已实施修复与定向回归

- InstallBusyError(RuntimeError)明确表示真实安装锁占用；InstallLock通过fstat检查锁文件长度，不读取其他进程锁住的第一个字节，锁API的忙错误与普通EIO分开，权限/IO问题不统一冒充另一个安装器。
- bootstrap先探测已有锁，再决定是否启动恢复；占用时返回2并显示“正在后台安装，请等待完成后自动重启”，不创建竞争恢复进程。无占用的遗留pending仍走原恢复。
- update_entry抢锁失败返回2，不写原安装器的共享结果、不执行恢复或重启、不弹“恢复未完成”。真实恢复错误仍保存失败结果/事务/备份，未伪造就绪或完成。
- 新增tests/test_active_install_startup.py：真实独立子进程持锁，6项原3PASS/3FAIL（6个失败断言），2.027秒，证明错误启动恢复/覆盖结果/误分类EIO。修复后连同更新入口、安装回滚及启动日志共20项4.284秒通过。
- 新测试产物使用1.3.8独立身份，不覆盖1.3.7包/用户安装目录。最终全量与冻结入口验证已完成，结果见下。

## 原安装的最终结果（只读核对）

- 原更新器自然完成，未执行手动recover、删除pending、改写实际结果、终止进程或重装。原结果最终为ok=true，pending由原安装器清除，voice_status实际检查installed=true、v2ProPlus-cu128-runtime-1、missing_count=0。
- 原更新器自动启动主程序PID29076；只读进程元数据显示Responding=true、MainWindowTitle=TachiTalk。没有替用户关闭该程序。证据work/voice-recovery-20261024/actual-completed.json。
- 这证实本次“打不开”发生在原安装尚未完成时的错误恢复竞争，不能将原截图当作安装包已损坏。旧竞争恢复写过的失败结果最终由真正的原安装成功结果替代。
- 独立审查额外发现元数据EACCES仍可能误归忙锁；补了先失败回归，并将忙分类限制于真实lock API调用。最终定向21项3.916秒通过，返回2契约已收紧断言。此前进行中的全量被本轮主动中止（只终止本轮测试进程，不涉及用户程序），改为补齐该回归后的502项最终全量；旧中间冻结输出不交付。
- 冻结回归首轮的腐损备份夹具有两个操作，错误地断言“后添加的新文件仍存在”；实际恢复按逆序先正确回滚该新增文件，再在早先腐损备份处失败。依据recover既有逆序语义修正夹具为新增文件已回滚、原替换目标/腐损备份/完整journal仍保留，并改用全新frozen-qa-final目录重跑；没有为迎合测试修改回滚业务。首轮verify-frozen.log保留。

## 最终冻结/原生验证

- 最终独立freeze目录release-final和probe-release-final完成后才启动验证，使用产品一致的干净PATH；辅助程序是控制台入口，异常写日志，不入安装包。
- 真冻结bootstrap辅助程序与产品app.bootstrap/app.updates.install代码对象相同；独立进程持有临时安装锁时返回2并显示明确安装中信息，没有创建恢复子进程。锁释放后陈旧pending仍创建恢复命令。
- 实际交付TachiTalkUpdater.exe在锁被占用时返回2，结果哨兵/journal不变；锁释放后真正恢复原文件、回滚新增文件并写ok=true；腐损备份场景返回1、保留原替换目标/备份/journal和可诊断错误。
- 同一产品Inno脚本编译独立Test安装器及无注册/快捷方式的QA安装器，原生安装在隔离目录；实际产品核心自检通过、界面SVG/ICO完整。验证结果frozen-qa-final/verification.json全部true。上述为小型事务夹具，不再次下载安装6.2GB语音；用户原完整安装成功另有实际证据。
- 独立审查work/voice-recovery-20261024/review.md无剩余阻塞问题；最终全量502项514.209秒通过（full-tests-final.log），定向21项3.916秒通过。中止的中间全量不计作最终结果。

## 交付与剩余实机验证

- 测试包：D:\TachiTalk\work\voice-recovery-20261024\delivery\TachiTalk-v1.3.8-install-recovery-test-main.zip；77,486,639字节；SHA256 `5a12650cc6095697211ec3a7e75493fe0ed387091e82ffc0f8ab0509a1db38b6`，配套.sha256.txt。独立Test身份/默认目录，保留旧测试包。ZIP CRC/成员、安装器与最终构建相同字节、生产公钥和配置、无QA辅助模块混入均通过。
- 精确基线packaging/baselines/main-1.3.8-install-recovery-test-inventory.json；可携带证据docs/release-evidence-1.3.8-install-recovery；新电脑源码/签名语音六文件/测试包复制清单HANDOFF_RTX5070.md。
- 本机已复现修复安装中重开错误恢复，原真实语音安装另有自然成功证据；没有重新下载安装6.2GB资源作为本轮冻结夹具。RTX5070 Laptop实际安装/首次聊天与重启聊天仍需新电脑确认，BUG1/4仍未在本机复现，不能宣称已完成目标GPU兼容验收。
- 全部未提交修改保留，HEAD4666ea0e1b3f255e4ee6276294e7582781f42414及stable-2026-10-22对象979a8fba7a18acaae7c579ed7795ddf75a08d9de/提交8eb0d2b145ea065ba23f8035abb94ac0c9036956不变。未提交/推送、未改稳定语音环境/信任链/云端/正式Release。
