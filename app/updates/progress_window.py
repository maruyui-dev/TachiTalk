"""Independent Qt viewer. Frozen updater loads Qt from its own onefile directory."""
import json
from pathlib import Path
import time
from threading import Thread

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                              QLabel, QProgressBar, QPlainTextEdit, QPushButton)
from app.updates.progress import process_alive

PHASES = {'starting': '准备安装', 'waiting': '等待主程序退出', 'manifest': '验证签名清单',
          'prepare': '准备安装', 'install': '安装文件',
          'archive': '验证归档', 'space': '检查安装空间', 'extract': '解压',
          'verify': '逐文件校验', 'backup': '备份', 'replace': '替换',
          'commit': '提交事务', 'cleanup': '清理安装材料', 'recovery': '恢复', 'restart': '重新启动主程序',
          'uninstall': '移除已校验的语音文件'}


def elapsed(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


class InstallProgressWindow(QWidget):
    def __init__(self, result, *, observer=False):
        super().__init__()
        self.result = Path(result)
        self.path = self.result.with_name('install-progress.json')
        self.observer = observer
        self.terminal = False
        self.state = {}
        self.closing_after_restart = False
        self.restart_close_timer = QTimer(self)
        self.restart_close_timer.setSingleShot(True)
        self.restart_close_timer.setInterval(2500)
        self.restart_close_timer.timeout.connect(self.close)
        self.setWindowTitle('TachiTalk · 安装进度' + ('（只读）' if observer else ''))
        self.resize(690, 470)
        self.setMinimumWidth(530)
        self.setStyleSheet('QWidget {background:#fff9fc; color:#473c44; font-size:14px}'
                           'QProgressBar {border:1px solid #dfcbd4; border-radius:5px; height:23px; text-align:center}'
                           'QProgressBar::chunk {background:#e78bae}'
                           'QPushButton {padding:7px 14px; background:#f6e4ed; border:1px solid #dfcbd4; border-radius:5px}')
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 20, 24, 20)
        self.heading = QLabel('正在读取安装事务…')
        self.heading.setStyleSheet('font-size:21px; font-weight:600')
        box.addWidget(self.heading)
        self.bar = QProgressBar()
        box.addWidget(self.bar)
        self.counter = QLabel('处理中')
        box.addWidget(self.counter)
        self.current = QLabel('')
        self.current.setWordWrap(True)
        box.addWidget(self.current)
        self.times = QLabel('')
        box.addWidget(self.times)
        self.notice = QLabel('安装中请保留此窗口；可最小化。关闭窗口不会取消安装。')
        self.notice.setWordWrap(True)
        box.addWidget(self.notice)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumBlockCount(80)
        self.diagnostics.hide()
        box.addWidget(self.diagnostics, 1)
        row = QHBoxLayout()
        copy = QPushButton('复制诊断信息')
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.diagnostics.toPlainText()))
        row.addWidget(copy)
        logs = QPushButton('打开日志目录')
        logs.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent))))
        row.addWidget(logs)
        details = QPushButton('诊断详情')
        details.setCheckable(True)
        details.toggled.connect(self.diagnostics.setVisible)
        row.addWidget(details)
        box.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self):
        try:
            state = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            self.bar.setRange(0, 0)
            self.notice.setText('尚未取得可读进度，不能确认工作是否推进。请查看安装结果和日志。')
            self.diagnostics.setPlainText(f'进度文件：{self.path}\n{type(error).__name__}: {error}')
            return
        if state.get('transaction') != self.state.get('transaction'):
            self.restart_close_timer.stop()
            self.closing_after_restart = False
        self.state = state
        s, now = self.state, time.time()
        status = s['status']
        self.terminal = status != 'running'
        self.heading.setText(PHASES.get(s['phase'], s['phase']))
        done, total = s.get('completed'), s.get('total')
        if total is not None and done is not None:
            percent = 100 if total == 0 else min(100, done * 100 / total)
            self.bar.setRange(0, 1000)
            self.bar.setValue(round(percent * 10))
            unit = '字节' if s['unit'] == 'bytes' else '个文件'
            self.counter.setText(f'{done:,} / {total:,} {unit} · {percent:.1f}%（本阶段）')
        else:
            self.bar.setRange(0, 0)
            self.counter.setText('处理中 · 本阶段无法确定总量')
        self.current.setText('当前文件：' + (s.get('current') or '—'))
        end = s.get('finished_at', now)
        self.times.setText(f"总耗时 {elapsed(end-s['started_at'])}    阶段耗时 {elapsed(end-s['phase_started_at'])}\n"
                           f"最近实际进度 {time.strftime('%H:%M:%S', time.localtime(s['progress_at']))}（{elapsed(now-s['progress_at'])}前）\n"
                           f"进程心跳 {time.strftime('%H:%M:%S', time.localtime(s['heartbeat_at']))}（心跳不代表工作推进）")
        notice = s.get('message', '安装中可最小化；完成前主进度窗口保持打开，不提供强制取消。')
        if status == 'running':
            if not process_alive(s.get('pid')):
                notice = '安装进程已退出，事务结果尚未确认。请保留备份和日志；再次启动程序将检查恢复。'
                self.diagnostics.show()
            elif now - s['progress_at'] >= 120:
                notice = '已超过 2 分钟没有实际进度；进程仍存在，无法仅凭心跳判定卡死。请复制诊断信息。'
                self.diagnostics.show()
        else:
            self.heading.setText({'succeeded': '安装成功', 'failed': '安装失败，已恢复原文件',
                                  'cleanup_pending': '安装成功，部分材料清理未完成',
                                  'recovery_failed': '恢复未完成', 'restart_failed': '安装已结束，自动启动失败'}.get(status, '安装已结束'))
            self.counter.setText('安装事务已成功提交' if status == 'succeeded' else '本次任务已结束，请查看结果与诊断信息')
            if self.bar.maximum() == 0:
                self.bar.setRange(0, 100)
                self.bar.setValue(100 if status == 'succeeded' else 0)
            notice += '；可以关闭此窗口。'
            if status != 'succeeded':
                self.diagnostics.show()
        self.notice.setText(notice)
        text = dict(s, result=str(self.result), progress=str(self.path),
                    seconds_without_progress=round(now-s['progress_at']),
                    seconds_in_phase=round(end-s['phase_started_at']))
        self.diagnostics.setPlainText(json.dumps(text, ensure_ascii=False, indent=2))
        if status == 'succeeded' and s.get('restarted') and not self.observer and not self.closing_after_restart:
            self.closing_after_restart = True
            self.restart_close_timer.start()

    def closeEvent(self, event):
        if self.observer or self.terminal:
            event.accept()
        else:
            self.notice.setText('安装仍在进行，主进度窗口暂不关闭；可最小化。关闭窗口不会取消安装。')
            event.ignore()


def show_progress(result, job=None):
    app = QApplication.instance() or QApplication([])
    window = InstallProgressWindow(result, observer=job is None)
    worker = None
    outcome = [0]
    if job is not None:
        def run():
            try:
                outcome[0] = job()
            except Exception as error:
                outcome[0] = 1
                outcome.append(f'{type(error).__name__}: {error}')
        worker = Thread(target=run, daemon=False)
        worker.start()
        def check_worker():
            if worker.is_alive():
                return
            if len(outcome) > 1 or outcome[0] == 2:
                window.observer = True
                window.notice.setText('另一个安装任务持有锁，仅查看原事务。' if outcome[0] == 2 else
                                     '更新器异常退出：' + outcome[1] + '。请保留事务和日志。')
                if len(outcome) > 1:
                    window.timer.stop()
                timer.stop()
        timer = QTimer(window)
        timer.timeout.connect(check_worker)
        timer.start(500)
    window.show()
    app.exec()
    if worker is not None:
        worker.join()
    return outcome[0]
