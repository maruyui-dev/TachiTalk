"""Resource connectivity and channel decisions, independent of app updates."""
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QHBoxLayout, QBoxLayout, QPlainTextEdit, QSizePolicy

from app.ui.update_page import STYLE, label, button, card


def network_icon(kind, size=44):
    if kind == 'modelscope':
        from app.paths import PROJECT_ROOT
        return QIcon(str(PROJECT_ROOT / 'resources/control_panel/assets/modelscope.ico'))
    paths = {
        'github': ('#24292f', '<path d="M12 .5a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2.2c-3.3.7-4-1.4-4-1.4-.5-1.4-1.3-1.8-1.3-1.8-1.1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1.1 1.8 2.8 1.3 3.4 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-6A4.7 4.7 0 0 1 5.5 8.5c-.1-.3-.5-1.6.1-3.3 0 0 1-.3 3.3 1.2a11.4 11.4 0 0 1 6 0c2.3-1.5 3.3-1.2 3.3-1.2.6 1.7.2 3 .1 3.3a4.7 4.7 0 0 1 1.2 3.3c0 4.7-2.8 5.7-5.5 6 .4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0 0 12 .5Z"/>'),
        'cloud': ('#f6821f', '<path d="M5 17a4 4 0 0 1 0-8 7 7 0 0 1 13.5-1A4.5 4.5 0 0 1 19.5 17Z"/><path d="M2 19h20v2H2Z"/>'),
        'globe': ('#69758b', '<g fill="none" stroke="#69758b" stroke-width="1.6"><circle cx="12" cy="12" r="10"/><ellipse cx="12" cy="12" rx="4" ry="10"/><path d="M2 12h20M4 6h16M4 18h16"/></g>'),
        'warning': ('#fff0cb', '<circle cx="12" cy="12" r="12"/><g fill="none" stroke="#c78015" stroke-width="1.4"><circle cx="12" cy="12" r="7"/><ellipse cx="12" cy="12" rx="3" ry="7"/><path d="M5 12h14M7 8h10M7 16h10"/></g>')}
    color, path = paths[kind]
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{color}">{path}</svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(svg.encode()).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def set_proxy_state(view, state, summary):
    """Use shape, color and text together; this reports settings, not tunnel health."""
    color, background, mark = {
        'detected': ('#23844c', '#e8f7ee', '<path d="m7 12 3 3 7-7"/>'),
        'not_found': ('#69758b', '#eef0f4', '<path d="M8 12h8"/>'),
        'unknown': ('#a96813', '#fff1d7', '<path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4m0 3v.1"/>')
    }.get(state, ('#69758b', '#eef0f4', ''))
    if mark:
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
            f'<circle cx="24" cy="24" r="24" fill="{background}"/>'
            f'<g transform="translate(12 12)" fill="none" stroke="{color}" stroke-width="2.2" '
            'stroke-linecap="round" stroke-linejoin="round">'
            '<path d="m12 2 9 4v6c0 6-9 10-9 10S3 18 3 12V6Z"/>' + mark + '</g></svg>')
        pixmap = QPixmap(112, 112)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(svg.encode()).render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(2)
        view.proxy_icon.setPixmap(pixmap)
    else:
        view.proxy_icon.setPixmap(network_icon('globe', 56).pixmap(56, 56))
    view.proxy_icon.setAccessibleName(summary)
    view.proxy_icon.setToolTip(summary)
    view.proxy_status.setText(summary)
    view.proxy_status.setStyleSheet(f'color: {color}; background: {background}; '
        'border-radius: 7px; padding: 5px 8px; font-weight: 600')


def build_network_card(view):
    frame, box = card()
    row = QHBoxLayout()
    row.addWidget(label('网络与下载源检测', title=True), 1)
    view.network_check_button = button('检测下载连接', view.detect_network)
    row.addWidget(view.network_check_button)
    box.addLayout(row)
    box.addWidget(label('新下载检测 GitHub 分卷首字节：< 250 ms 使用 GitHub，否则使用魔搭。继续任务保留已有来源。', muted=True))
    view.network_row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
    for kind, title, name, initial, detail in (
            ('modelscope', '魔搭 · ModelScope', 'modelscope', '尚未检测', '公开语音仓库 · 无需注册'),
            ('github', 'GitHub', 'github', '尚未检测', '清单与语音分卷分别检测'),
            ('globe', '代理状态', 'proxy', '尚未检测', '其他代理方式可能无法自动识别')):
        tile, column = card()
        row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(network_icon(kind).pixmap(44, 44))
        if name == 'modelscope':
            icon.setAccessibleName('魔搭社区 ModelScope')
            view.modelscope_icon = icon
        if name == 'proxy':
            view.proxy_icon = icon
        row.addWidget(icon)
        texts = QVBoxLayout()
        texts.addWidget(label(title))
        status = label(initial, title=True)
        setattr(view, name + '_status', status)
        texts.addWidget(status)
        sub = label(detail, muted=True)
        sub.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        setattr(view, name + '_detail', sub)
        texts.addWidget(sub)
        row.addLayout(texts, 1)
        column.addLayout(row)
        view.network_row.addWidget(tile, 1)
    set_proxy_state(view, 'unchecked', '尚未检测')
    box.addLayout(view.network_row)
    view.network_note = label('资源前缀连通检测不代表完整下载、签名或文件校验已通过。', muted=True)
    view.network_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    box.addWidget(view.network_note)
    return frame


def probe_description(probe):
    state = probe.get('state', 'unknown')
    if state == 'ok':
        latency = probe.get('latency_ms')
        return '可访问' + (f' · {latency:.2f} ms' if latency is not None else '')
    return {'timeout': '连接 / 读取超时', 'error': '访问失败', 'unknown': '未完成检测'}.get(state, '未完成检测')


def show_network_result(view, result):
    manifest, artifact = result['manifest'], result['artifact']
    mirror = result.get('modelscope')
    view.modelscope_status.setText(probe_description(mirror['artifact']) if mirror else '本次未检测')
    view.modelscope_detail.setText(('清单：' + probe_description(mirror['manifest']) + '\n分卷：' +
        probe_description(mirror['artifact'])) if mirror else '公开仓库 · 需要下载时独立解析入口')
    if result['state'] == 'ok':
        view.github_status.setText(probe_description(artifact))
        view.github_status.setStyleSheet('color: #23844c')
    else:
        view.github_status.setText('连接超时' if any(p.get('state') == 'timeout' for p in (manifest, artifact)) else
            '检测未完成' if result['state'] == 'unknown' else '资源访问异常')
        view.github_status.setStyleSheet('color: #a96813')
    view.github_detail.setText(f'清单：{probe_description(manifest)}\n分卷：{probe_description(artifact)}')
    set_proxy_state(view, result['proxy']['state'], result['proxy']['summary'])
    view.proxy_detail.setText('只识别代理设置，无法确认实际路由或全部代理方式')
    view.network_note.setText(f"检测于 {datetime.now():%H:%M:%S} · 耗时含连接、重定向及首字节；检测不代表完整安装验收。")


class NetworkPrompt(QDialog):
    retry_requested = Signal()
    continue_requested = Signal()
    modelscope_requested = Signal()

    def __init__(self, result, parent=None, *, can_continue=False):
        super().__init__(parent)
        self.setWindowTitle('TachiTalk · 下载连接检测')
        self.setStyleSheet(STYLE)
        self.resize(760, 630)
        self.setMinimumWidth(560)
        self.setWindowIcon(network_icon('globe', 32))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        from app.ui.control_panel import make_icon
        row = QHBoxLayout()
        cat = QLabel()
        cat.setPixmap(make_icon('cat', '#e95392', 30).pixmap(30, 30))
        row.addWidget(cat)
        row.addWidget(label('下载连接检测', title=True), 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(network_icon('warning', 64).pixmap(64, 64))
        row.addWidget(icon)
        heading = QVBoxLayout()
        channel = result.get('channel', 'GitHub')
        self.heading = label(channel + '连接失败' if result['state'] == 'failed' else '暂未取得可信语音清单', title=True)
        self.heading.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.heading.setStyleSheet('font-size: 23px; font-weight: 700')
        heading.addWidget(self.heading)
        proxy_state = result['proxy']['state']
        self.explanation = label('暂时无法连接或确认语音资源下载地址。\n' + result['proxy']['summary'] + '。', muted=True)
        heading.addWidget(self.explanation)
        heading.addWidget(label('其他代理方式可能无法自动识别；检测不到设置不等于一定没有代理。', muted=True))
        row.addLayout(heading, 1)
        layout.addLayout(row)
        diagnostics, box = card()
        for text, value in [(channel + '清单', probe_description(result['manifest'])),
                (channel + '语音分卷', probe_description(result['artifact'])), ('代理状态', result['proxy']['summary'])]:
            row = QHBoxLayout()
            row.addWidget(label(text), 1)
            row.addWidget(label(value), 2)
            box.addLayout(row)
        layout.addWidget(diagnostics)
        recommendation, box = card()
        recommendation.setStyleSheet('QFrame[deliveryCard="true"] {background: #f5f3ff; border: 1px solid #c4baff; border-radius: 10px;}')
        row = QHBoxLayout()
        cloud_icon = QLabel()
        cloud_icon.setPixmap(network_icon('modelscope', 64).pixmap(64, 64))
        cloud_icon.setAccessibleName('魔搭社区 ModelScope')
        row.addWidget(cloud_icon)
        content = QVBoxLayout()
        content.addWidget(label('魔搭公开语音仓库', title=True))
        content.addWidget(label('无需注册即可获取相同语音资源。手动切换来源会先停止旧任务，\n清理本任务缓存后从零下载；暂停或普通继续下载保留缓存。', muted=True))
        row.addLayout(content, 1)
        box.addLayout(row)
        layout.addWidget(recommendation)
        layout.addWidget(label('下载源切换保留生产签名、大小、分卷和整包 SHA256 校验。', muted=True))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(130)
        self.details.setAccessibleName('网络检测详细结果')
        self.details.setPlainText('\n'.join(f"{name}: {result[key].get('detail', probe_description(result[key]))}"
            for name, key in [('GitHub 清单', 'manifest'), ('GitHub 分卷', 'artifact')]) +
            '\n' + result.get('manifest_error', ''))
        self.details.hide()
        row = QHBoxLayout()
        self.details_button = button('查看检测详情', lambda: self.details.setVisible(not self.details.isVisible()))
        self.details_button.setProperty('deliveryLink', True)
        row.addWidget(self.details_button)
        row.addStretch()
        self.continue_button = button('仍尝试现有下载源', self.continue_requested.emit)
        self.continue_button.setEnabled(can_continue)
        row.addWidget(self.continue_button)
        layout.addLayout(row)
        layout.addWidget(self.details)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button('取消安装', self.reject))
        self.retry_button = button('重新检测', self.retry_requested.emit)
        row.addWidget(self.retry_button)
        self.modelscope_button = button('改用魔搭', self.modelscope_requested.emit, primary=True)
        row.addWidget(self.modelscope_button)
        layout.addLayout(row)
