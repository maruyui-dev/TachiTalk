"""退出自动保存、启动恢复。资源库已有独立持久化，不用旧快照覆盖新资源。"""
import base64
from copy import deepcopy
import logging

from PySide6.QtCore import QByteArray, QObject
from PySide6.QtWidgets import QCheckBox, QLineEdit, QPlainTextEdit, QStackedWidget

from app.core.configuration_profiles import check_active_profiles, parse_profiles
from app.core.session_file import SessionFile
from app.ui.configuration_services import apply_profiles, capture_profiles, commit_ai, commit_audio

LOG = logging.getLogger('tachitalk.settings')
PAGES = ('characterPage', 'dialoguePage', 'audioPage', 'aiPage', 'resourcesPage', 'trainingPage', 'deliveryPage')


class SessionControls(QObject):
    def __init__(self, panel, path):
        super().__init__(panel)
        self.panel = panel
        self.file = SessionFile(path)
        self.recovery = SessionFile(self.file.path.with_name('last_session.recovered.dat'))
        self.preserve_original = False
        self.loaded = False
        self.pet_visible = True
        self.restore_attempted = False
        panel.closing.connect(self.save)

    def snapshot(self):
        audio = self.panel.audio_resource_controls
        selected = audio.selected()
        draft = None
        if audio.page is not None and audio._dirty and selected is not None:
            draft = {'name': audio.w('audioNicknameEdit', QLineEdit).text(),
                     'scene': audio.w('audioSceneEdit', QLineEdit).text(),
                     'prompt': audio.w('audioPromptEdit', QPlainTextEdit).toPlainText(),
                     'enabled': audio.w('audioEnabledCheck', QCheckBox).isChecked(),
                     'default': audio.w('audioDefaultCheck', QCheckBox).isChecked()}
        return {'format': 'TachiTalk.session', 'version': 1,
                'pages': self.panel.settings_controls.values.capture(),
                'profiles': capture_profiles(self.panel),
                'desktop': self.panel.settings_controls.desktop_snapshot(),
                'view': {'geometry': bytes(self.panel.saveGeometry().toBase64()).decode('ascii'),
                         'docks': bytes(self.panel.saveState().toBase64()).decode('ascii'),
                         'page': self.panel.findChild(QStackedWidget, 'pageStack').currentWidget().objectName(),
                         'audio_tab': audio.tabs.currentIndex(), 'audio_pack': audio.library.active_id,
                         'audio_selected': selected.key if selected else None,
                         'audio_search': audio.w('audioSearchEdit', QLineEdit).text() if audio.page is not None else '',
                         'audio_draft': draft}}

    def prepare(self, document):
        if (not isinstance(document, dict) or set(document) != {'format', 'version', 'pages', 'profiles', 'desktop', 'view'}
                or document['format'] != 'TachiTalk.session' or type(document['version']) is not int
                or document['version'] != 1):
            raise ValueError('自动配置版本或结构不正确')
        settings = self.panel.settings_controls
        settings.values.validate(document['pages'])
        # 保留用户尚未填完的地址；服务是否可用仍由现有后台预检判断。
        profiles = parse_profiles(document['profiles'], allow_incomplete=True)
        check_active_profiles(document['pages'], profiles)
        settings.validate_desktop(document['desktop'])
        view = document['view']
        if (not isinstance(view, dict) or set(view) != {'geometry', 'docks', 'page', 'audio_tab', 'audio_pack',
                'audio_selected', 'audio_search', 'audio_draft'} or view['page'] not in PAGES
                or type(view['audio_tab']) is not int or view['audio_tab'] not in (0, 1)
                or not isinstance(view['audio_pack'], str) or len(view['audio_pack']) > 64
                or view['audio_selected'] is not None and (not isinstance(view['audio_selected'], str)
                                                         or len(view['audio_selected']) > 64)
                or not isinstance(view['audio_search'], str) or len(view['audio_search']) > 16384):
            raise ValueError('自动配置的面板状态无效')
        for name in ('geometry', 'docks'):
            if not isinstance(view[name], str) or len(view[name]) > 65536:
                raise ValueError('自动配置的窗口状态过大')
            base64.b64decode(view[name], validate=True)
        draft = view['audio_draft']
        if draft is not None and (not isinstance(draft, dict) or set(draft) != {'name', 'scene', 'prompt', 'enabled', 'default'}
                or any(not isinstance(draft[name], str) or len(draft[name]) > 16384 for name in ('name', 'scene', 'prompt'))
                or type(draft['enabled']) is not bool or type(draft['default']) is not bool):
            raise ValueError('自动配置的音频编辑草稿无效')
        return profiles

    def apply(self, document, profiles):
        settings = self.panel.settings_controls
        pages = deepcopy(document['pages'])
        resources = self.panel.resource_controls
        if pages['characterPage']['expressionCombo'] not in resources.library.active_expressions:
            pages['characterPage']['expressionCombo'] = resources.library.base.default
        apply_profiles(self.panel, profiles)
        for values in pages.values():
            settings.values.put(values)
        commit_ai(self.panel, pages['aiPage'])
        commit_audio(self.panel, pages['audioPage'])
        self.panel.persona_controls.update_profile()
        settings.commit_character(pages['characterPage'], document['desktop'])
        resources.scope_changed()
        resources.filter_rows()
        view = document['view']
        self.panel.restoreGeometry(QByteArray(base64.b64decode(view['geometry'])))
        self.panel.restoreState(QByteArray(base64.b64decode(view['docks'])))
        self.panel.select_page(PAGES.index(view['page']), show_notice=False)
        audio = self.panel.audio_resource_controls
        audio.tabs.setCurrentIndex(view['audio_tab'])
        if audio.page is not None:
            if view['audio_pack'] == audio.library.active_id:
                audio.refresh(view['audio_selected'])
                if view['audio_draft'] is not None and audio.selected() is not None and audio.selected().key == view['audio_selected']:
                    draft = view['audio_draft']
                    for name, field in (('audioNicknameEdit', 'name'), ('audioSceneEdit', 'scene')):
                        audio.w(name, QLineEdit).setText(draft[field])
                    audio.w('audioPromptEdit', QPlainTextEdit).setPlainText(draft['prompt'])
                    audio.w('audioEnabledCheck', QCheckBox).setChecked(draft['enabled'])
                    audio.w('audioDefaultCheck', QCheckBox).setChecked(draft['default'])
                    audio.mark_dirty()
            audio.w('audioSearchEdit', QLineEdit).setText(view['audio_search'])
        self.pet_visible = document['desktop']['visible']

    def restore(self):
        self.restore_attempted = True
        for source in (self.file, self.recovery):
            try:
                document = source.read()
                if document is None:
                    continue
                prepared = self.prepare(document)
                previous = self.snapshot()
                try:
                    self.apply(document, prepared)
                except Exception:
                    self.apply(previous, self.prepare(previous))
                    raise
                self.loaded = True
                self.panel.settings_controls.report('已恢复上次关闭时的界面设置', quiet=True)
                return True
            except (OSError, ValueError, TypeError, KeyError, RuntimeError, AttributeError) as error:
                if source is self.file:
                    self.preserve_original = True
                # 不记录配置内容、密钥或解密后的原始数据。
                LOG.warning('自动恢复失败（%s）；原文件保留', type(error).__name__)
        if self.preserve_original:
            self.panel.settings_controls.report('上次自动配置无法读取，已保留原文件；本次设置将另存恢复文件', error=True)
        return False

    def save(self):
        try:
            audio = self.panel.audio_resource_controls
            if audio._dirty:
                try:
                    audio.save()
                except (OSError, ValueError):
                    LOG.warning('音频编辑尚未通过保存校验，将作为草稿保留')
            document = self.snapshot()
            self.prepare(document)
            target = self.recovery if self.preserve_original else self.file
            target.write(document)
            LOG.debug('已自动保存界面设置')
            return True
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, AttributeError) as error:
            self.panel.settings_controls.report(f'自动保存失败（{type(error).__name__}），原配置文件保留', error=True)
            return False
