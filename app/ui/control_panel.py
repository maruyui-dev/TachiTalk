"""控制面板：接入角色显示及运行日志，其他控件按批次连接。"""
import sys
import logging
from functools import partial
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QObject, QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImageReader, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QHeaderView, QLabel, QMainWindow,
    QPushButton, QStackedWidget, QTableWidget,
)
from app.ui.character_controls import CharacterControls
from app.ui.bubble_preview import BubblePreview
from app.ui.character_preview import PortraitPreview, PreviewCanvas
from app.ui.conversation_controls import ConversationControls
from app.ui.persona_controls import PersonaControls
from app.ui.audio_controls import AudioControls
from app.ui.voice_controls import VoiceControls
from app.ui.ai_controls import AIControls
from app.ui.resource_controls import ResourceControls
from app.ui.audio_resource_controls import AudioResourceControls
from app.core.audio_library import AudioLibrary
from app.core.resources import ResourceLibrary
from app.core.portrait_packs import PackResources
from app.ui.runtime_console import RuntimeConsole
from app.ui.training_page import TrainingPage
from app.ui.settings_controls import SettingsControls
from app.paths import ASSET_DIR, BUBBLE_DIR, PROJECT_ROOT, DATA_ROOT, FROZEN

# 只从TachiTalk项目内读取界面资源，不依赖原来的“训练”文件夹。
BASE_DIR = PROJECT_ROOT / 'resources' / 'control_panel'
RESOURCE_STATE = DATA_ROOT / 'resources' / 'resource_library.json' if FROZEN else BASE_DIR.parent / 'resource_library.json'
RESOURCE_DIRECTORY = DATA_ROOT / 'assets' if FROZEN else ASSET_DIR
RESOURCE_BUBBLE_DIRECTORY = DATA_ROOT / 'bubbles' if FROZEN else BUBBLE_DIR
if FROZEN:
    for directory in (RESOURCE_STATE.parent, RESOURCE_DIRECTORY, RESOURCE_BUBBLE_DIRECTORY):
        directory.mkdir(parents=True, exist_ok=True)


class ControlPanelWindow(QMainWindow):
    """主窗口负责发出整个程序的关闭请求。"""
    closing = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._closing = False
        # 应用级过滤可覆盖后续动态创建的资源映射下拉框；范围仅限本面板。
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.Wheel
                and isinstance(watched, (QComboBox, QAbstractSpinBox))
                and self.isAncestorOf(watched)):
            event.ignore()  # 交给父级滚动页面，不让控件切选项或增减数值。
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        if not self._closing:
            self._closing = True
            self.closing.emit()
        super().closeEvent(event)


class ControlPanelLoader(QUiLoader):
    """沿用Designer布局，让根窗口具备手写的关闭信号。"""
    def createWidget(self, class_name, parent=None, name=''):
        if name == 'previewCanvas':
            widget = PreviewCanvas(parent)
            widget.setObjectName(name)
            return widget
        if class_name == 'QMainWindow' and parent is None:
            window = ControlPanelWindow()
            window.setObjectName(name)
            return window
        return super().createWidget(class_name, parent, name)


# 用简单SVG路径绘制统一的线条图标，无需安装图标库。
ICON_PATHS = {
    'person': '<circle cx="12" cy="7" r="3"/><path d="M4 21v-2a8 8 0 0 1 16 0v2Z"/>',
    'chat': '<path d="M4 4h16v12H9l-5 4Z"/><path d="M8 9h8M8 12h5"/>',
    'audio': '<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/>',
    'settings': '<path d="m9 3-1 3-3 1 1 4-2 2 2 4 3-1 3 3 3-3 3 1 2-4-2-2 1-4-3-1-1-3Z"/><circle cx="12" cy="11" r="3"/>',
    'folder': '<path d="M3 6h7l2 3h9v11H3Z"/><path d="M3 6V4h7l2 2h8v3"/>',
    'send': '<path d="m3 10 18-7-7 18-3-8Z"/><path d="m11 13 10-10"/>',
    'eye': '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    'cat': '<path d="m4 10 1-8 6 5h2l6-5 1 8a8 8 0 0 1-16 0Z"/><path d="M8 12h.1M16 12h.1m-5 3 1 1 1-1M1 13l5 1m12 0 5-1M2 17l4-1m12 0 4 1"/>',
    'terminal': '<rect x="2" y="4" width="20" height="16" rx="3"/><path d="m6 9 3 3-3 3m7 0h5"/>',
    'training': '<path d="M4 20V11h4v9Zm6 0V4h4v16Zm6 0V8h4v12Z"/>',
    'upload': '<path d="M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5"/>',
    'headphones': '<path d="M4 13v-2a8 8 0 0 1 16 0v2M4 11h3v9H4Zm13 0h3v9h-3Z"/>',
}


def make_icon(name, color='#677184', size=24):
    """把SVG字符串绘制到透明QPixmap，再转成Qt图标。"""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
           f'viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
           f'{ICON_PATHS[name]}</svg>')
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(svg.encode('utf-8')).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


class PreviewImage(QObject):
    """只管理预览图片随标签大小缩放；不会控制桌面人物。"""
    render_scale_changed = Signal(float)

    def __init__(self, label):
        super().__init__(label)
        self.label = label
        image = QPixmap(str(ASSET_DIR / '生气.png'))
        if image.isNull():
            raise FileNotFoundError(f'缺少 {ASSET_DIR / "生气.png"}，无法显示人物预览')
        self.full_image = image
        self.reference_image = image.copy(0, 0, image.width(), round(image.height() * 0.5))
        self.scale_percent, self.display_percent = 180, 50
        self.preview_ratio = 1.0
        self.image = self.reference_image
        self.source = None
        self.whole_image = False
        self.empty = False
        label.installEventFilter(self)
        QTimer.singleShot(0, self.fit)

    def fit(self):
        if self.empty:
            self.label.clear()
            return
        if self.label.width() > 0 and self.label.height() > 0:
            if self.whole_image:
                self.label.setPixmap(self.full_image.scaled(self.label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                           Qt.TransformationMode.SmoothTransformation))
                return
            reference = self.reference_image.scaled(
                self.label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            ratio = self.scale_percent / 180
            width = max(1, reference.width() * ratio)
            height = max(1, reference.height() * ratio * self.display_percent / 50)
            fit = min(1.0, self.label.width() / width, self.label.height() / height)
            self.label.setPixmap(self.image.scaled(
                max(1, round(width * fit)), max(1, round(height * fit)),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            ))
            # 预览空间不足时统一适配，气泡也使用同一倍率。
            if abs(self.preview_ratio - ratio * fit) > 0.001:
                self.preview_ratio = ratio * fit
                self.render_scale_changed.emit(self.preview_ratio)

    def set_display_options(self, scale_percent, display_percent):
        if (self.scale_percent, self.display_percent) == (scale_percent, display_percent):
            return
        self.scale_percent, self.display_percent = scale_percent, display_percent
        self.image = self.full_image.copy(0, 0, self.full_image.width(),
                                          max(1, round(self.full_image.height() * display_percent / 100)))
        self.fit()

    def set_source(self, path, whole=False):
        path = Path(path)
        signature = (path, whole, path.stat().st_mtime_ns, path.stat().st_size)
        if self.source == signature:
            return
        image = QPixmap.fromImage(QImageReader(str(path)).read())
        if image.isNull():
            raise ValueError(f'无法预览图片：{path.name}')
        self.source = signature
        self.whole_image = whole
        self.empty = False
        self.full_image = image
        self.reference_image = image.copy(0, 0, image.width(), max(1, round(image.height() * 0.5)))
        self.image = image.copy(0, 0, image.width(), max(1, round(image.height() * self.display_percent / 100)))
        self.fit()

    def clear(self):
        self.empty = True
        self.source = None
        self.label.clear()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.fit()
        return super().eventFilter(watched, event)


def setup_navigation(window):
    """侧栏切换页面；开发中的训练页先提示，再进入预览。"""
    pages = (
        ('navCharacter', 'person', '角色控制', '调整人物与气泡的显示方式', '设置实时预览'),
        ('navChat', 'chat', '对话设置', '配置角色人设与日常对话偏好', '人设与对话偏好'),
        ('navAudio', 'audio', '语音与音频', '配置录音、语音识别和语音播放', '输入与输出设备'),
        ('navAI', 'settings', 'AI 服务', '配置模型接口，调整生成参数', '模型服务配置'),
        ('navAssets', 'folder', '资源管理', '整理本地立绘、气泡皮肤与神态映射', '立绘与气泡素材'),
        ('navTraining', 'training', '模型训练', '使用 GPT-SoVITS，为角色训练专属声音', '功能开发中，仅供界面预览；暂不支持训练'),
    )
    stack = window.findChild(QStackedWidget, 'pageStack')

    def select_page(index, _checked=False, *, show_notice=True):
        training = index == stack.indexOf(window.training_page.page)
        if training and show_notice:
            current_name = pages[stack.currentIndex()][0]
            window.findChild(QPushButton, current_name).setChecked(True)
            window.training_page.show_notice()
            if window._closing:
                return
        _, _, title, subtitle, footer = pages[index]
        stack.setCurrentIndex(index)
        window.findChild(QLabel, 'pageTitle').setText(title)
        window.findChild(QLabel, 'pageSubtitle').setText(subtitle)
        window.findChild(QLabel, 'footerHint').setText(footer)
        window.findChild(QPushButton, 'hideButton').setVisible(index == 0)
        window.findChild(QPushButton, 'resetPositionButton').setVisible(index == 0)
        window.training_page.actions.setVisible(training)
        window.setWindowTitle('TachiTalk · ' + title)
        for position, (name, icon, *_rest) in enumerate(pages):
            button = window.findChild(QPushButton, name)
            button.setChecked(position == index)
            button.setIcon(make_icon(icon, '#d55c8d' if position == index else '#677184'))
        logging.getLogger('tachitalk.ui').info('切换页面：%s', title)

    for index, (name, *_rest) in enumerate(pages):
        window.findChild(QPushButton, name).clicked.connect(partial(select_page, index))
    window.select_page = select_page
    select_page(0)


def load_window(startup_records=(), pet=None, library=None, audio_library=None, remember=False):
    """.ui负责控件和布局；QSS负责颜色、字体、边框和状态。"""
    ui_file = QFile(str(BASE_DIR / 'character_control.ui'))
    if not ui_file.open(QIODevice.OpenModeFlag.ReadOnly):
        raise FileNotFoundError(f'无法打开界面文件：{ui_file.fileName()}')
    loader = ControlPanelLoader()
    window = loader.load(ui_file)
    ui_file.close()
    if window is None:
        raise RuntimeError(f'界面加载失败：{loader.errorString()}')
    window.training_page = TrainingPage(window, BASE_DIR / 'model_training.ui')
    qss = (BASE_DIR / 'character_control.qss').read_text(encoding='utf-8')
    window.setStyleSheet(qss.replace('@ASSETS@', (BASE_DIR / 'assets').as_posix())
                        .replace('@BUBBLES@', BUBBLE_DIR.as_posix()))
    window.setWindowIcon(make_icon('cat', '#ec709d', 32))

    nav_icons = {'navCharacter': 'person', 'navChat': 'chat', 'navAudio': 'audio',
                 'navAI': 'settings', 'navAssets': 'folder', 'navTraining': 'training'}
    for name, icon in nav_icons.items():
        button = window.findChild(QPushButton, name)
        button.setIcon(make_icon(icon, '#d55c8d' if name == 'navCharacter' else '#677184'))
        button.setIconSize(QSize(23, 23))
    for name, icon in {'personIcon': 'person', 'bubbleIcon': 'chat',
                       'sendIcon': 'send', 'previewIcon': 'eye'}.items():
        window.findChild(QLabel, name).setPixmap(make_icon(icon).pixmap(21, 21))
    window.findChild(QLabel, 'brandIcon').setPixmap(make_icon('cat', '#ec709d', 40).pixmap(40, 40))
    window.findChild(QLabel, 'footerIcon').setPixmap(make_icon('settings', '#8b93a4', 18).pixmap(18, 18))
    log_button = window.findChild(QPushButton, 'navRuntimeLog')
    log_button.setIcon(make_icon('terminal'))
    log_button.setIconSize(QSize(23, 23))
    for label in window.findChildren(QLabel):
        icon = label.property('iconName')
        if icon:
            label.setPixmap(make_icon(icon).pixmap(21, 21))
    # 保存引用，避免Python提前回收负责图片缩放的对象。
    window.preview_image = PreviewImage(window.findChild(QLabel, 'avatarLabel'))
    window.portrait_preview = PortraitPreview(window)
    window.resource_preview_image = PreviewImage(window.findChild(QLabel, 'resourceAvatarLabel'))
    table = window.findChild(QTableWidget, 'resourceTable')
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(44)
    table.selectRow(0)
    window.bubble_preview = BubblePreview(window)
    window.bubble_preview.set_options(4, 4, 1.0)
    window.runtime_console = RuntimeConsole(window, startup_records=startup_records)
    setup_navigation(window)
    window.findChild(QLabel, 'visibleStatus').setText('●  角色未连接')
    for kind, name in ((QPushButton, 'hideButton'), (QCheckBox, 'topCheck'), (QCheckBox, 'fixedCheck')):
        window.findChild(kind, name).setEnabled(False)
    if pet is not None:
        window.character_controls = CharacterControls(window, pet)
    window.conversation_controls = ConversationControls(window)
    window.persona_controls = PersonaControls(window)
    window.audio_controls = AudioControls(window)
    window.voice_controls = VoiceControls(window)
    window.ai_controls = AIControls(window)
    if library is None:
        from config import REF_MAP
        library = ResourceLibrary(RESOURCE_DIRECTORY, RESOURCE_STATE, expressions=REF_MAP)
    if not isinstance(library, PackResources):
        library = PackResources(library, bubble_directory=RESOURCE_BUBBLE_DIRECTORY)
    window.resource_controls = ResourceControls(window, pet, library)
    if audio_library is None:
        from config import REF_MAP
        audio_library = AudioLibrary(DATA_ROOT / 'resources' / 'audio_library.json', REF_MAP)
    window.audio_resource_controls = AudioResourceControls(window, audio_library, BASE_DIR / 'audio_resources.ui')
    window.settings_controls = SettingsControls(window, RESOURCE_DIRECTORY, RESOURCE_BUBBLE_DIRECTORY)
    if remember:
        remember_session(window)
    return window


def remember_session(window):
    """桌面入口在绑定运行对象后、启动后台前调用；纯预览/测试可选择不启用。"""
    from app.ui.session_controls import SessionControls
    window.session_controls = SessionControls(window, DATA_ROOT / 'settings' / 'last_session.dat')
    window.session_controls.restore()


def main():
    app = QApplication(sys.argv)
    window = load_window(remember=True)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
