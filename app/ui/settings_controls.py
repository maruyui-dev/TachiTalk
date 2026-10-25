"""页内恢复默认、全局配置备份与加载；不包含任何模型训练实现。"""
from copy import deepcopy
from dataclasses import replace
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QSignalBlocker
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton, QStackedWidget

from app.core.configuration_file import FORMAT, VERSION, check_envelope, read_config, write_config
from app.core.configuration_profiles import parse_profiles, check_active_profiles
from app.core.resource_configuration import capture_resources, prepare_resources, apply_resources
from app.core.audio_library import AudioLibrary
from app.core.settings_defaults import PAGE_DEFAULTS, DESKTOP_DEFAULTS, RESOURCE_DEFAULTS, KEY_FIELDS
from app.ui.configuration_widgets import ConfigurationWidgets
from app.ui.configuration_services import capture_profiles, profile_objects, apply_profiles, commit_ai, commit_audio


class SettingsControls(QObject):
    def __init__(self, panel, resource_directory, bubble_directory):
        super().__init__(panel)
        self.panel = panel
        self.resource_directory, self.bubble_directory = resource_directory, bubble_directory
        self.values = ConfigurationWidgets(panel)
        panel.findChild(QPushButton, 'resetButton').clicked.connect(self.reset_current)
        panel.findChild(QPushButton, 'saveButton').clicked.connect(self.choose_save)
        panel.findChild(QPushButton, 'loadSettingsButton').clicked.connect(self.choose_load)
        panel.findChild(QPushButton, 'resetButton').setToolTip('只恢复当前页；清空本页所有服务的API Key，保留导入图片')
        panel.findChild(QPushButton, 'saveButton').setToolTip('选择位置，备份全部页面设置；文件包含API Key，请妥善保管')

    def report(self, message, error=False, *, quiet=False):
        self.panel.findChild(QLabel, 'footerHint').setText(message)
        logger = logging.getLogger('tachitalk.settings')
        (logger.error if error else logger.debug if quiet else logger.info)(message)

    def desktop_snapshot(self):
        controls = getattr(self.panel, 'character_controls', None)
        pet = controls.pet if controls else None
        def preview(color):
            document = QTextDocument()
            document.setHtml(self.panel.findChild(QLabel, color + 'Preview').text())
            return document.toPlainText()
        desktop = {'visible': pet.isVisible() if pet else True,
                   'anchor': list(pet.anchor) if pet and pet.anchor is not None else None,
                   'position': [pet.x(), pet.y()] if pet else [0, 0],
                   'layout_anchor': list(pet._layout_anchor) if pet else [2, 2],
                   'preview': {color: preview(color) for color in ('pink', 'blue')}}
        return desktop

    def snapshot(self):
        return {'format': FORMAT, 'version': VERSION, 'pages': self.values.capture(),
                'profiles': capture_profiles(self.panel), 'desktop': self.desktop_snapshot(),
                'resources': capture_resources(self.panel.resource_controls.library),
                'audio_resources': deepcopy(self.panel.audio_resource_controls.library.state)}

    def prepare(self, document):
        check_envelope(document)
        self.values.validate(document['pages'])
        profiles = parse_profiles(document['profiles'])
        check_active_profiles(document['pages'], profiles)
        self.validate_desktop(document['desktop'])
        resources = prepare_resources(self.panel.resource_controls.library, document['resources'])
        if 'audio_resources' in document:
            AudioLibrary.validate(document['audio_resources'])
        catalog = resources[0][resources[2]['active']].catalog()
        if document['pages']['characterPage']['expressionCombo'] not in catalog.names:
            raise ValueError('配置中的当前神态不存在于所选角色包')
        return profiles, resources

    @staticmethod
    def validate_desktop(desktop):
        if (set(desktop) != {'visible', 'anchor', 'position', 'layout_anchor', 'preview'}
                or type(desktop['visible']) is not bool):
            raise ValueError('角色桌面状态格式不正确')
        for key, bound in (('anchor', 2), ('layout_anchor', 2), ('position', 100000)):
            value = desktop[key]
            if key == 'anchor' and value is None:
                continue
            if (not isinstance(value, list) or len(value) != 2
                    or any(type(v) is not int or abs(v) > bound or key != 'position' and v < 0 for v in value)):
                raise ValueError('角色位置参数不正确')
        if (not isinstance(desktop['preview'], dict) or set(desktop['preview']) != {'pink', 'blue'}
                or any(not isinstance(v, str) or len(v) > 300 for v in desktop['preview'].values())):
            raise ValueError('气泡预览文本格式不正确')

    def commit_character(self, values, desktop):
        controls = getattr(self.panel, 'character_controls', None)
        if controls:
            pet = controls.pet
            # 批量设置时暂缓回读，避免旧显示范围反过来覆盖新控件值。
            with QSignalBlocker(pet):
                pet.set_scale_percent(values['scaleSlider'])
                pet.set_display_percent((50, 100, values['rangeSlider'])[values['rangeCombo']])
                pet.set_max_bubbles(values['maxBubblesSpin'])
                pet.set_bubble_gap(values['bubbleGapSpin'])
                pet.set_stays_on_top(values['topCheck'])
                pet.set_position_fixed(values['fixedCheck'])
                if desktop['anchor'] is not None:
                    pet.set_anchor(*desktop['anchor'])
                else:
                    pet.restore_manual_position(*desktop['position'], desktop['layout_anchor'])
                pet.setVisible(desktop['visible'])
            controls._range_mode = values['rangeCombo']
            controls._custom_percent = values['rangeSlider']
            controls.sync()
        else:
            self.panel.preview_image.set_display_options(values['scaleSlider'],
                (50, 100, values['rangeSlider'])[values['rangeCombo']])
            self.panel.bubble_preview.set_options(values['maxBubblesSpin'], values['bubbleGapSpin'], 1.0)
        self.panel.resource_controls.preview_expression(values['expressionCombo'])
        self.panel.conversation_controls.set_recording(values['recordingEnabledCheck'])
        for color, text in desktop['preview'].items():
            self.panel.bubble_preview.set_message(color, text)

    def apply_document(self, document, prepared):
        profiles, resource_plan = prepared
        if 'audio_resources' in document:
            audio = self.panel.audio_resource_controls
            audio.library._commit(deepcopy(document['audio_resources']))
            audio.refresh()
        controls = self.panel.resource_controls
        apply_resources(controls.library, resource_plan)
        # 先更新可选神态/资源，再回填配置中选定的神态，避免被资源刷新覆盖。
        controls.refresh()
        controls.apply()
        apply_profiles(self.panel, profiles)
        for values in document['pages'].values():
            self.values.put(values)
        commit_ai(self.panel, document['pages']['aiPage'])
        commit_audio(self.panel, document['pages']['audioPage'])
        self.panel.persona_controls.update_profile()
        self.commit_character(document['pages']['characterPage'], document['desktop'])
        with QSignalBlocker(controls.table):
            controls.table.clearSelection()
            controls.table.setCurrentCell(-1, -1)
        controls.refresh()
        controls.filter_rows()

    def reset_current(self):
        page = self.panel.findChild(QStackedWidget, 'pageStack').currentWidget().objectName()
        values = deepcopy(PAGE_DEFAULTS[page])
        values.update({name: '' for name in KEY_FIELDS.get(page, ())})
        try:
            if page == 'aiPage':
                c = self.panel.ai_controls
                c._cache = {name: replace(options, api_key='') for name, options in c._cache.items()}
                self.values.put(values)
                commit_ai(self.panel, values)
            elif page == 'audioPage':
                c = self.panel.voice_controls
                c._asr_cache = {name: replace(options, api_key='') for name, options in c._asr_cache.items()}
                c._tts_cache = {name: replace(options, api_key='') for name, options in c._tts_cache.items()}
                self.values.put(values)
                commit_audio(self.panel, values)
            elif page == 'resourcesPage':
                audio = self.panel.audio_resource_controls
                if audio.tabs.currentIndex() == 1:
                    if audio.leave_editor():
                        audio.library.select_pack('default')
                        audio.refresh()
                        self.report('已回到初始音频包；保留音频编辑和立绘设置')
                    return
                library = self.panel.resource_controls.library
                data = capture_resources(library)
                data['active'] = RESOURCE_DEFAULTS['active_pack']
                data['packs']['default']['name'] = RESOURCE_DEFAULTS['default_pack_name']
                for state, directory in ((data['packs']['default']['state'], self.resource_directory),
                                         (data['bubbles'], self.bubble_directory)):
                    state.update(directory=str(directory), mapping={}, skins={}, excluded=[])
                prepared = prepare_resources(library, data)
                apply_resources(library, prepared)
                self.values.put(values)
                controls = self.panel.resource_controls
                with QSignalBlocker(controls.table):
                    controls.table.clearSelection()
                    controls.table.setCurrentCell(-1, -1)
                self.panel.resource_controls.refresh()
                self.panel.resource_controls.apply()
                # Session restore deliberately excludes resource mappings; persist
                # the reset here so the next process cannot reload the old files.
                library.save()
            else:
                self.values.put(values)
                if page == 'characterPage':
                    self.commit_character(values, deepcopy(DESKTOP_DEFAULTS))
                elif page == 'dialoguePage':
                    self.panel.persona_controls.update_profile()
            self.report('当前页已恢复默认，本页API Key已清空；其余页面及导入图片保留')
        except (ValueError, OSError, RuntimeError) as error:
            self.report('恢复默认失败：' + str(error), error=True)

    def choose_save(self):
        filename, _ = QFileDialog.getSaveFileName(self.panel,
            '保存全部设置（包含API Key，请妥善保管）', 'TachiTalk.tachitalk.json', 'TachiTalk配置 (*.json)')
        if filename:
            self.save_to(filename if Path(filename).suffix.lower() == '.json' else filename + '.json')

    def save_to(self, filename):
        try:
            audio = self.panel.audio_resource_controls
            if audio._dirty:
                audio.save()
            document = self.snapshot()
            self.prepare(document)
            write_config(filename, document)
        except (OSError, ValueError, TypeError, RuntimeError) as error:
            self.report('配置保存失败：' + str(error), error=True)
            QMessageBox.warning(self.panel, '配置保存失败', str(error))
            return False
        self.report('全部页面设置已保存；配置文件包含API Key，请妥善保管')
        return True

    def choose_load(self):
        filename, _ = QFileDialog.getOpenFileName(self.panel, '加载全部页面设置', '', 'TachiTalk配置 (*.json)')
        if filename:
            self.load_from(filename)

    def load_from(self, filename):
        failure_note = '原设置未修改'
        try:
            document = read_config(filename)
            prepared = self.prepare(document)  # 完整校验成功之前不改动任何页面或运行设置。
            previous = self.snapshot()
            library = self.panel.resource_controls.library
            old_packs = {'default': library.original, **library._loaded_libraries, library.active_id: library.active}
            old_prepared = profile_objects(self.panel), (old_packs, library.global_resources, deepcopy(library.manifest))
            try:
                self.apply_document(document, prepared)
            except Exception:
                try:
                    self.apply_document(previous, old_prepared)
                    failure_note = '原设置已恢复'
                except Exception:
                    failure_note = '无法完整恢复，请检查本机资源文件并重新加载配置'
                raise
        except (OSError, ValueError, TypeError, RuntimeError) as error:
            self.report('配置加载失败，' + failure_note + '：' + str(error), error=True)
            QMessageBox.warning(self.panel, '配置加载失败', str(error))
            return False
        self.report('全部页面配置已加载并应用；图片和训练模型仍使用本机已有文件')
        return True
