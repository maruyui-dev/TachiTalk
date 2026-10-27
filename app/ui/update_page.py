"""Presentation widgets for delivery; network and installation stay in UpdateControls."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QBoxLayout, QProgressBar, QPlainTextEdit, QSizePolicy)


STYLE = '''
QDialog { background: #fcfcfe; }
QWidget#deliveryPage, QWidget#deliveryContent { background: transparent; }
QFrame[deliveryCard="true"] { background: white; border: 1px solid #e1e5ee; border-radius: 10px; }
QLabel { color: #263248; background: transparent; border: none; font-size: 13px; }
QLabel[deliveryTitle="true"] { font-size: 18px; font-weight: 600; color: #1d2940; }
QLabel[deliveryMuted="true"] { color: #68758b; }
QLabel[deliveryBadge="true"] { background: #fff0f6; color: #bd4c7d; border-radius: 10px; padding: 5px 9px; }
QLabel[deliveryGood="true"] { color: #23844c; }
QPushButton { background: white; color: #263248; border: 1px solid #d3d9e4; border-radius: 7px; padding: 8px 12px; }
QPushButton:hover { background: #fff4f8; border-color: #e89fbb; }
QPushButton:focus { border: 2px solid #df6b98; }
QPushButton:disabled { background: #f6f7fa; color: #929bac; border-color: #e4e7ee; }
QPushButton[deliveryPrimary="true"] { background: #e95392; color: white; border-color: #e95392; }
QPushButton[deliveryPrimary="true"]:hover { background: #db4483; }
QPushButton[deliveryPrimary="true"]:disabled { background: #f6c0d6; border-color: #f6c0d6; color: #8c4a66; }
QPushButton[deliveryLink="true"] { color: #b34572; border: none; background: transparent; }
QProgressBar { border: none; border-radius: 6px; background: #e9ebf1; min-height: 12px; max-height: 12px; }
QProgressBar::chunk { background: #ed5a9b; border-radius: 6px; }
QPlainTextEdit { background: white; border: 1px solid #e1e5ee; border-radius: 8px; padding: 12px; }
'''


def label(text='', *, title=False, muted=False):
    item = QLabel(text)
    item.setTextFormat(Qt.TextFormat.PlainText)
    item.setWordWrap(True)
    item.setProperty('deliveryTitle', title)
    item.setProperty('deliveryMuted', muted)
    return item


def button(text, slot, *, primary=False):
    item = QPushButton(text)
    item.setProperty('deliveryPrimary', primary)
    item.clicked.connect(slot)
    return item


def card():
    frame = QFrame()
    frame.setProperty('deliveryCard', True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)
    return frame, layout


class DiskRing(QWidget):
    """The pink arc represents used capacity; center text reports available capacity."""
    def __init__(self):
        super().__init__()
        self.total, self.free = 0, 0
        self.setFixedSize(142, 142)
        self.setAccessibleName('安装磁盘容量')

    def set_usage(self, total, free):
        self.total, self.free = total, free
        self.setAccessibleDescription(f'总容量 {total} 字节，可用 {free} 字节')
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(12, 12, 118, 118)
        pen = QPen(QColor('#e7e9ef'), 14)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(rect)
        if self.total:
            pen.setColor(QColor('#ec609c'))
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, -round(360 * 16 * (1 - self.free / self.total)))
        painter.setPen(QColor('#253148'))
        font = QFont(self.font())
        font.setPointSize(17)
        font.setBold(True)
        painter.setFont(font)
        text = f'{self.free / self.total:.1%}' if self.total else '—'
        painter.drawText(QRectF(10, 44, 122, 34), Qt.AlignmentFlag.AlignCenter, text)
        font.setPointSize(11)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor('#69758b'))
        painter.drawText(QRectF(10, 80, 122, 25), Qt.AlignmentFlag.AlignCenter, '可用')
        painter.end()


def build_page(view):
    from app.ui.control_panel import make_icon
    view.setObjectName('deliveryPage')
    view.setStyleSheet(STYLE)
    view.setWidgetResizable(True)
    view.setFrameShape(QFrame.Shape.NoFrame)
    content = QWidget()
    content.setObjectName('deliveryContent')
    view.setWidget(content)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 8, 4)
    layout.setSpacing(12)

    main, box = card()
    row = QHBoxLayout()
    cat = QLabel()
    cat.setPixmap(make_icon('cat', '#e95392', 48).pixmap(48, 48))
    row.addWidget(cat)
    info = QVBoxLayout()
    info.addWidget(label('TachiTalk 主程序', title=True))
    view.main_status = label('尚未检查更新', muted=True)
    info.addWidget(view.main_status)
    row.addLayout(info, 1)
    view.check_button = button('检查更新 · 暂未开放', view.check)
    view.update_button = button('更新主程序', view.update_main, primary=True)
    row.addWidget(view.check_button)
    row.addWidget(view.update_button)
    view.notes_button = button('查看更新记录', view.show_release_notes)
    view.notes_button.setProperty('deliveryLink', True)
    row.addWidget(view.notes_button)
    box.addLayout(row)
    view.main_detail = label('', muted=True)
    view.main_detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    box.addWidget(view.main_detail)
    layout.addWidget(main)

    from app.ui.update_network import build_network_card
    layout.addWidget(build_network_card(view))

    view.resource_row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
    view.resource_row.setSpacing(12)
    voice, box = card()
    row = QHBoxLayout()
    row.addWidget(label('可选语音组件', title=True), 1)
    view.voice_state = label('尚未检查')
    view.voice_state.setProperty('deliveryBadge', True)
    row.addWidget(view.voice_state)
    box.addLayout(row)
    view.voice_version = label('GPT-SoVITS v2ProPlus', muted=True)
    box.addWidget(view.voice_version)
    box.addWidget(label('安装后可使用角色语音合成，文字对话与立绘不受影响。', muted=True))
    view.voice_detail = label('', muted=True)
    view.voice_detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    box.addWidget(view.voice_detail)
    row = QHBoxLayout()
    for heading, name in [('下载大小', 'download_size'), ('安装预留', 'install_size')]:
        column = QVBoxLayout()
        column.addWidget(label(heading, muted=True))
        item = label('检查后显示', title=True)
        setattr(view, name, item)
        column.addWidget(item)
        row.addLayout(column, 1)
    box.addLayout(row)
    row = QHBoxLayout()
    view.import_button = button('导入离线资源', view.import_local)
    view.legacy_button = button('复用旧版语音', view.select_legacy)
    view.install_button = button('安装 / 修复语音资源', view.install_voice, primary=True)
    for item in (view.import_button, view.legacy_button, view.install_button):
        row.addWidget(item)
    box.addLayout(row)
    box.addWidget(label('点击后先检测资源连接，再开始下载。', muted=True))
    view.preparation_hint = label('', muted=True)
    view.preparation_hint.setAccessibleName('首次下载准备提示')
    view.preparation_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    view.preparation_hint.setStyleSheet('font-size: 12px; color: #8f641e; background: #fff7e8; '
        'border-radius: 6px; padding: 7px')
    box.addWidget(view.preparation_hint)
    view.preparation_hint.hide()
    view.resource_row.addWidget(voice, 3)

    training, training_box = card()
    training_box.addWidget(label('v2ProPlus 完整训练包', title=True))
    view.training_state = label('', muted=True)
    training_box.addWidget(view.training_state)
    training_box.addWidget(label('按需安装切分、自动标注、人声分离的工具与权重及训练底模，复用已有推理环境。', muted=True))
    training_box.addWidget(button('下载 / 修复完整训练包', view.install_training))
    training_box.addWidget(button('卸载托管训练扩展', view.remove_training))
    layout.addWidget(training)

    disk, box = card()
    view.disk_title = label('安装磁盘', title=True)
    box.addWidget(view.disk_title)
    row = QHBoxLayout()
    view.disk_ring = DiskRing()
    row.addWidget(view.disk_ring)
    view.disk_details = label('', muted=True)
    row.addWidget(view.disk_details, 1)
    box.addLayout(row)
    view.space_state = label('检查资源后确认空间要求')
    box.addWidget(view.space_state)
    view.resource_row.addWidget(disk, 2)
    layout.addLayout(view.resource_row)

    task, box = card()
    row = QHBoxLayout()
    row.addWidget(label('下载任务', title=True), 1)
    view.task_count = label('暂无任务', muted=True)
    row.addWidget(view.task_count)
    box.addLayout(row)
    view.task_title = label('安装或更新资源后，下载进度会显示在这里')
    view.task_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    box.addWidget(view.task_title)
    row = QHBoxLayout()
    view.progress_bar = QProgressBar()
    view.progress_bar.setRange(0, 1000)
    view.progress_bar.setTextVisible(False)
    view.percent_label = label('0%')
    row.addWidget(view.progress_bar, 1)
    row.addWidget(view.percent_label)
    box.addLayout(row)
    row = QHBoxLayout()
    view.transfer_details = label('— / —　·　速度 —', muted=True)
    view.eta_label = label('预计剩余 —', muted=True)
    row.addWidget(view.transfer_details, 1)
    row.addWidget(view.eta_label)
    box.addLayout(row)
    row = QHBoxLayout()
    view.source_label = label('来源：自动选择', muted=True)
    view.source_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    view.switch_button = button('切换来源', view.select_source)
    view.pause_button = button('暂停', view.pause)
    view.cancel_button = button('取消', view.cancel_download)
    view.retry_button = button('继续下载', view.retry)
    for item in (view.source_label, view.switch_button, view.pause_button, view.cancel_button, view.retry_button):
        row.addWidget(item)
    box.addLayout(row)
    box.addWidget(label('暂停或取消保留缓存；切换来源会清理当前任务缓存，从 0% 重新下载。', muted=True))
    view.state = label('就绪；未安装语音时可继续使用文字对话', muted=True)
    # A long URL/exception must wrap within the viewport, never become its minimum width.
    view.state.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    view.state.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    box.addWidget(view.state)
    layout.addWidget(task)

    location, box = card()
    row = QHBoxLayout()
    row.addWidget(label('安装位置', title=True))
    badge = label('与主程序同目录')
    badge.setProperty('deliveryBadge', True)
    row.addWidget(badge)
    row.addStretch()
    box.addLayout(row)
    view.location_details = label('', muted=True)
    view.location_details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    view.location_details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    box.addWidget(view.location_details)
    box.addWidget(label('新增资源默认安装在主程序目录内。当前资源无需单独选择安装根目录。', muted=True))
    layout.addWidget(location)

    view.settings_button = button('下载设置　　官方优先 · 失败后自动尝试备用源　 ›', view.open_settings)
    view.settings_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    layout.addWidget(view.settings_button)
    layout.addWidget(label('公共代理的可用性无法保证，可在下载设置中关闭。', muted=True))
    layout.addStretch()

    # The editor belongs to the settings dialog, never to the ordinary install flow.
    view.config = QPlainTextEdit(view)
    view.config.setAccessibleName('高级下载源配置 JSON')
    view.config.hide()
    view.clear_button = button('删除下载缓存', view.clear_cache)
    view.clear_button.hide()
    view.uninstall_button = button('卸载托管语音组件', view.remove_voice)
    view.uninstall_button.hide()
