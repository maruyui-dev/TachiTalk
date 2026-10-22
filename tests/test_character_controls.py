"""验证真实Qt控件、窗口切换及全身立绘拖动，不启动语音服务。"""
import unittest
from time import monotonic

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QMouseEvent, QPalette, QPixmap, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSlider, QSpinBox

from app.ui.desktop_pet import DesktopPetWindow
from app.ui.control_panel import load_window


class CharacterControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        if not QFontDatabase.families():
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')

    def setUp(self):
        self.pet = DesktopPetWindow()
        self.pet.ANIMATION_MS = 1
        self.panel = load_window(pet=self.pet)
        self.pet.show()
        self.panel.show()
        self.app.processEvents()
        self.fixed = self.panel.findChild(QCheckBox, 'fixedCheck')
        self.top = self.panel.findChild(QCheckBox, 'topCheck')
        self.hide = self.panel.findChild(QPushButton, 'hideButton')
        self.status = self.panel.findChild(QLabel, 'visibleStatus')

    def test_persona_defaults_and_edits_reach_the_shared_profile(self):
        language = self.panel.findChild(QComboBox, 'replyLanguageCombo')
        self.assertEqual([language.itemText(i) for i in range(language.count())], ['简体中文', '英文', '日文'])
        controls = self.panel.persona_controls
        profile = controls.profiles.snapshot()
        self.assertEqual((profile.character_name, profile.user_name, profile.reply_language, profile.persona_prompt),
                         ('茉子', '', '简体中文', ''))
        self.panel.findChild(QLineEdit, 'characterNameEdit').setText('小夏')
        self.panel.findChild(QLineEdit, 'userNameEdit').setText('阿明')
        self.panel.findChild(QPlainTextEdit, 'personaEdit').setPlainText('用简短直接的语气说话。')
        language.setCurrentText('英文')
        changed = controls.profiles.snapshot()
        self.assertEqual((changed.character_name, changed.user_name, changed.reply_language, changed.persona_prompt),
                         ('小夏', '阿明', '英文', '用简短直接的语气说话。'))
        self.assertEqual(profile.character_name, '茉子', '已交给当前回复的快照不能被界面修改')
        self.panel.findChild(QPlainTextEdit, 'personaEdit').clear()
        self.assertEqual(controls.profiles.snapshot().persona_prompt, '')

    def test_preview_keeps_portrait_proportions_when_window_is_widened(self):
        from PySide6.QtWidgets import QWidget
        card = self.panel.findChild(QWidget, 'previewCard')
        self.panel.resize(1200, 920)
        self.app.processEvents()
        narrow = card.size()
        self.panel.resize(1800, 920)
        self.app.processEvents()
        self.assertAlmostEqual(card.width() / card.height(), narrow.width() / narrow.height(), delta=.02)
        self.assertLess(card.width() / card.height(), .70)
        self.assertLess(card.width(), 600)
        avatar = self.panel.findChild(QLabel, 'avatarLabel')
        self.assertLess(avatar.width() - avatar.pixmap().width(), 160)

    def test_dialogue_preferences_remove_duplicates_and_update_profile(self):
        for name in ('typewriterCheck', 'typingIntervalSpin', 'messageDurationSpin'):
            self.assertIsNone(self.panel.findChild(QObject, name))
            self.assertIsNone(self.panel.findChild(QObject, name + 'Caption'))
        stream = self.panel.findChild(QCheckBox, 'streamReplyCheck')
        expressions = self.panel.findChild(QCheckBox, 'expressionLinkCheck')
        context = self.panel.findChild(QComboBox, 'contextTurnsCombo')
        self.assertTrue(stream.isChecked())
        self.assertTrue(expressions.isChecked())
        profile = self.panel.persona_controls.profiles.snapshot()
        self.assertEqual((profile.stream_reply, profile.switch_expression, profile.context_turns), (True, True, 20))
        stream.setChecked(False)
        expressions.setChecked(False)
        context.setCurrentText('最近 5 轮')
        profile = self.panel.persona_controls.profiles.snapshot()
        self.assertEqual((profile.stream_reply, profile.switch_expression, profile.context_turns), (False, False, 5))

    def test_streaming_caption_relay_keeps_latest_without_queuing_each_fragment(self):
        from threading import Thread
        from app.ui.desktop import CaptionRelay, DesktopSignals
        signals = DesktopSignals()
        relay = CaptionRelay(self.pet)
        relay.timer.stop()
        signals.caption.connect(relay.offer, Qt.ConnectionType.DirectConnection)

        def produce():
            for i in range(2000):
                signals.caption.emit(5, f'当前文字{i}')

        worker = Thread(target=produce)
        worker.start()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.pet.bubbles, [])
        relay.flush()
        QTest.qWait(20)
        self.assertEqual([card.text for card in self.pet.bubbles], ['当前文字1999'])
        signals.caption.emit(4, '旧轮次不应覆盖')
        relay.flush()
        self.assertEqual(self.pet.bubbles[-1].text, '当前文字1999')
        relay.close()
        signals.caption.emit(6, '关闭后忽略')
        relay.flush()
        self.assertEqual(self.pet.bubbles[-1].text, '当前文字1999')

    def tearDown(self):
        self.pet.shutdown()
        self.panel.close()
        self.pet.deleteLater()
        self.panel.deleteLater()
        self.app.processEvents()

    def drag(self, local, delta):
        # 使用不随窗口移动而变化的屏幕坐标，验证连续拖动不会累积偏移。
        origin = self.pet.mapToGlobal(local)
        events = (
            (QEvent.Type.MouseButtonPress, origin, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseMove, origin + delta, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseButtonRelease, origin + delta, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
        )
        for kind, global_pos, button, buttons in events:
            event = QMouseEvent(kind, QPointF(self.pet.mapFromGlobal(global_pos)),
                                QPointF(global_pos), button, buttons, Qt.KeyboardModifier.NoModifier)
            self.app.sendEvent(self.pet, event)

    def body_point(self, fraction=0.25):
        image = self.pet.character.image_rect()
        return self.pet.character.pos() + QPoint(image.center().x(), round(image.height() * fraction))

    def test_fixed_free_and_fixed_again_keep_the_chosen_position(self):
        original = self.pet.pos()
        self.drag(self.body_point(), QPoint(-35, -50))
        self.assertEqual(self.pet.pos(), original)
        self.fixed.click()
        self.drag(self.body_point(), QPoint(-35, -50))
        chosen = original + QPoint(-35, -50)
        self.assertEqual(self.pet.pos(), chosen)
        self.fixed.click()
        self.drag(self.body_point(), QPoint(-20, -30))
        self.pet.resize(self.pet.width() - 10, self.pet.height())
        self.app.processEvents()
        self.assertEqual(self.pet.pos(), chosen, '重新固定或重绘不能把立绘弹回右下角')

    def test_full_body_preset_keeps_the_complete_image_when_dragged(self):
        # 新需求规定拖动时也遵守显示范围，因此先明确选择全身。
        self.panel.findChild(QComboBox, 'rangeCombo').setCurrentIndex(1)
        character = self.pet.character
        source = QPixmap(str(character.catalog.paths[character.current_expression]))
        displayed = character.ui.petLable.pixmap()
        self.assertAlmostEqual(displayed.width() / displayed.height(),
                               source.width() / source.height(), delta=0.003)
        self.assertTrue(self.pet.rect().contains(character.geometry()), '完整身体必须放在父窗口内')
        area = self.app.primaryScreen().availableGeometry()
        self.assertLessEqual(character.mapToGlobal(character.rect().bottomRight()).y(), area.bottom())
        self.fixed.click()
        delta = QPoint(-40, area.top() + 20 - character.mapToGlobal(QPoint()).y())
        self.drag(self.body_point(), delta)
        self.assertGreaterEqual(character.mapToGlobal(QPoint()).y(), area.top())
        self.assertLessEqual(character.mapToGlobal(character.rect().bottomRight()).y(), area.bottom())
        position = self.pet.pos()
        self.drag(self.body_point(0.85), QPoint(12, 15))
        self.assertEqual(self.pet.pos(), position + QPoint(12, 15), '露出的下半身也应能拖动')

    def test_hidden_badge_is_amber_and_shown_badge_is_green(self):
        self.hide.click()
        self.assertEqual(self.status.palette().color(QPalette.ColorRole.WindowText).name(), '#b77917')
        self.hide.click()
        self.assertEqual(self.status.palette().color(QPalette.ColorRole.WindowText).name(), '#4b9c6c')

    def test_scale_changes_existing_and_future_bubbles_with_character(self):
        self.pet.add_transcript('同步缩放')
        QTest.qWait(40)
        old_card = self.pet.bubbles[-1]
        body_before = self.pet.character.height()
        bubble_before = old_card.size()
        font_before = old_card.ui.messageLabel.font().pointSizeF()
        self.panel.findChild(QSlider, 'scaleSlider').setValue(90)
        self.assertEqual(self.panel.findChild(QLabel, 'scaleValue').text(), '90%')
        self.assertAlmostEqual(self.pet.character.height() / body_before, 0.5, delta=0.01)
        self.assertAlmostEqual(old_card.width() / bubble_before.width(), 0.5, delta=0.035)
        self.assertAlmostEqual(old_card.height() / bubble_before.height(), 0.5, delta=0.035)
        self.assertAlmostEqual(old_card.ui.messageLabel.font().pointSizeF() / font_before, 0.5, delta=0.01)
        self.pet.add_transcript('同步缩放')
        QTest.qWait(40)
        self.assertEqual(self.pet.bubbles[-1].size(), old_card.size(), '新消息必须使用当前缩放比例')
        old_card.set_message('更新后的长文字也必须保持当前字号。' * 5)
        self.assertAlmostEqual(old_card.ui.messageLabel.font().pointSizeF() / font_before, 0.5, delta=0.01)

    def test_range_slider_reveals_top_to_bottom_and_drag_keeps_it(self):
        combo = self.panel.findChild(QComboBox, 'rangeCombo')
        slider = self.panel.findChild(QSlider, 'rangeSlider')
        self.assertIsNotNone(slider, '自定义显示范围需要真实滑块')
        self.assertFalse(slider.isVisible())
        half_height = self.pet.character.height()
        combo.setCurrentIndex(1)
        self.assertAlmostEqual(self.pet.character.height() / half_height, 2, delta=0.01)
        full_width = self.pet.character.ui.petLable.pixmap().width()
        combo.setCurrentIndex(2)
        self.assertTrue(slider.isVisible())
        slider.setValue(25)
        quarter_height = self.pet.character.height()
        slider.setValue(75)
        self.assertAlmostEqual(self.pet.character.height() / quarter_height, 3, delta=0.03)
        self.assertAlmostEqual(self.pet.character.ui.petLable.pixmap().width(), full_width, delta=2)
        image_before = self.pet.character.ui.petLable.pixmap().toImage()
        self.fixed.click()
        self.drag(self.body_point(), QPoint(-50, -100))
        self.assertEqual(self.pet.character.ui.petLable.pixmap().toImage(), image_before)

    def test_all_nine_anchors_position_the_visible_portrait(self):
        area = self.app.primaryScreen().availableGeometry()
        for row in range(3):
            for column in range(3):
                with self.subTest(row=row, column=column):
                    self.panel.findChild(QPushButton, f'anchor{row}{column}').click()
                    body = self.pet.character.image_rect().translated(self.pet.character.mapToGlobal(QPoint()))
                    if column == 0:
                        self.assertLess(abs(body.left() - area.left()), 25)
                    elif column == 1:
                        self.assertLess(abs(body.center().x() - area.center().x()), 3)
                    else:
                        self.assertLess(abs(body.right() - area.right()), 25)
                    if row == 0:
                        self.assertLess(abs(body.top() - area.top()), 25)
                    elif row == 1:
                        self.assertLess(abs(body.center().y() - area.center().y()), 3)
                    else:
                        self.assertLess(abs(body.bottom() - area.bottom()), 25)
                    self.assertTrue(self.fixed.isChecked(), '固定位置不应阻止主动点击九宫格定位')

    def test_manual_drag_clears_grid_selection_and_reset_returns_to_corner(self):
        self.fixed.click()
        self.drag(self.body_point(), QPoint(-90, -65))
        self.assertIn('自定义', self.panel.findChild(QLabel, 'positionValue').text())
        self.assertFalse(any(self.panel.findChild(QPushButton, f'anchor{r}{c}').isChecked()
                             for r in range(3) for c in range(3)))
        self.panel.findChild(QPushButton, 'resetButton').click()
        self.assertTrue(self.panel.findChild(QPushButton, 'anchor22').isChecked())

    def test_person_margin_controls_are_removed(self):
        for name in ('rightMarginSpin', 'bottomMarginSpin', 'rightMarginCaption', 'bottomMarginCaption'):
            self.assertIsNone(self.panel.findChild(QObject, name))

    def test_quick_dialogue_changes_only_the_selected_preview_bubble(self):
        edit = self.panel.findChild(QPlainTextEdit, 'messageEdit')
        pink = self.panel.findChild(QLabel, 'pinkPreview')
        blue = self.panel.findChild(QLabel, 'bluePreview')
        old_pink = pink.text()
        self.panel.findChild(QPushButton, 'chooseBlueButton').click()
        edit.setPlainText('预览测试 <b>原样显示</b>')
        self.panel.findChild(QPushButton, 'sendButton').click()
        self.assertIn('预览测试', blue.text())
        self.assertIn('&lt;b&gt;', blue.text())
        self.assertEqual(pink.text(), old_pink)
        self.assertEqual(self.pet.bubbles, [], '预览测试不能发送真实对话或修改桌面聊天记录')

    def test_recording_switch_shows_text_input_and_busy_send_keeps_draft(self):
        from app.core.conversation_input import ConversationInput
        from app.ui.desktop import DesktopSignals
        signals = DesktopSignals(self.panel)
        inputs = ConversationInput(on_change=signals.input_state.emit)
        inputs.set_service_ready('LLM')
        inputs.set_service_ready('TTS')
        controls = self.panel.conversation_controls
        controls.bind_inputs(inputs, signals)
        toggle = self.panel.findChild(QCheckBox, 'recordingEnabledCheck')
        edit = self.panel.findChild(QPlainTextEdit, 'textConversationEdit')
        send = self.panel.findChild(QPushButton, 'textConversationSend')
        self.assertFalse(edit.isVisible())
        toggle.click()
        self.assertTrue(edit.isVisible())
        self.assertTrue(send.isEnabled())
        edit.setPlainText('输入文字进行交流')
        send.click()
        self.assertEqual(inputs.take_next().payload, '输入文字进行交流')
        self.assertEqual(edit.toPlainText(), '')
        edit.setPlainText('回复中保留草稿')
        controls.send_text()
        self.assertEqual(edit.toPlainText(), '回复中保留草稿')
        self.assertFalse(send.isEnabled())
        inputs.finish_turn()
        self.app.processEvents()
        self.assertTrue(send.isEnabled())
        toggle.click()
        self.assertFalse(edit.isVisible())
        toggle.click()
        self.assertEqual(edit.toPlainText(), '回复中保留草稿')

    def wait_for_bubbles(self):
        deadline = monotonic() + 3
        while self.pet._animating or self.pet._pending_messages:
            self.assertLess(monotonic(), deadline, '气泡动画和待显示消息未及时完成')
            QTest.qWait(5)

    def test_bubble_limit_trims_oldest_and_applies_to_future_messages(self):
        for number in range(4):
            self.pet.add_transcript(str(number))
            self.wait_for_bubbles()
        maximum = self.panel.findChild(QSpinBox, 'maxBubblesSpin')
        maximum.setValue(2)
        self.assertEqual([card.text for card in self.pet.bubbles], ['2', '3'])
        self.pet.add_transcript('4')
        self.wait_for_bubbles()
        self.assertEqual([card.text for card in self.pet.bubbles], ['3', '4'])
        maximum.setValue(5)
        for number in range(5, 8):
            self.pet.add_transcript(str(number))
            self.wait_for_bubbles()
        self.assertEqual([card.text for card in self.pet.bubbles], ['3', '4', '5', '6', '7'])
        maximum.setValue(1)
        self.assertFalse(self.panel.findChild(QLabel, 'pinkPreview').isVisible())
        self.assertTrue(self.panel.findChild(QLabel, 'bluePreview').isVisible())

    def test_gap_controls_visible_edges_in_pet_and_preview(self):
        self.pet.add_message('pink', '粉色')
        self.wait_for_bubbles()
        self.pet.add_message('blue', '蓝色')
        self.wait_for_bubbles()
        spin = self.panel.findChild(QSpinBox, 'bubbleGapSpin')
        for gap in (0, 24, 80):
            spin.setValue(gap)
            QTest.qWait(30)
            older, newer = self.pet.bubbles
            older_bottom = older.y() + older.visible_rect.bottom()
            newer_top = newer.y() + newer.visible_rect.top()
            self.assertEqual(newer_top - older_bottom - 1, gap)
            rectangles = []
            for name in ('pinkPreview', 'bluePreview'):
                label = self.panel.findChild(QLabel, name)
                pixmap = label.grab()
                bounds = QRegion(pixmap.mask()).boundingRect()
                ratio = pixmap.devicePixelRatio()
                rectangles.append((label.mapToGlobal(QPoint()).y() + bounds.top() / ratio,
                                   label.mapToGlobal(QPoint()).y() + (bounds.bottom() + 1) / ratio))
            actual_gap = rectangles[1][0] - rectangles[0][1]
            expected = round(gap * self.panel.preview_image.preview_ratio)
            self.assertAlmostEqual(actual_gap, expected, delta=1)
        self.pet.set_scale_percent(90)
        older, newer = self.pet.bubbles
        self.assertEqual(newer.y() + newer.visible_rect.top() - older.y() - older.visible_rect.bottom() - 1, 40)

    def test_limit_change_during_animation_preserves_latest_and_pending_bound(self):
        self.pet.ANIMATION_MS = 20
        maximum = self.panel.findChild(QSpinBox, 'maxBubblesSpin')
        for number in range(25):
            self.pet.add_transcript(str(number))
            if number == 10:
                maximum.setValue(1)
            self.assertLessEqual(len(self.pet.bubbles), maximum.value())
            self.assertLessEqual(len(self.pet._pending_messages), 8)
        self.wait_for_bubbles()
        self.assertEqual([card.text for card in self.pet.bubbles], ['24'])

    def test_many_widely_spaced_bubbles_fit_the_transparent_parent(self):
        self.panel.findChild(QSpinBox, 'maxBubblesSpin').setValue(10)
        self.panel.findChild(QSpinBox, 'bubbleGapSpin').setValue(100)
        for number in range(10):
            self.pet.add_transcript(str(number))
            self.wait_for_bubbles()
        self.assertEqual(len(self.pet.bubbles), 10)
        for card in self.pet.bubbles:
            self.assertTrue(self.pet.bubble_area.rect().contains(card.visible_rect.translated(card.pos())))

    def test_scaling_during_animation_keeps_queues_bounded_and_latest_messages(self):
        self.pet.ANIMATION_MS = 20
        for number in range(30):
            self.pet.add_transcript(str(number))
            if number == 10:
                self.pet.set_scale_percent(120)
                self.pet.set_display_percent(80)
            self.assertLessEqual(len(self.pet.bubbles), 4)
            self.assertLessEqual(len(self.pet._pending_messages), 8)
        for _ in range(100):
            if not self.pet._animating and not self.pet._pending_messages:
                break
            QTest.qWait(10)
        self.assertFalse(self.pet._animating)
        self.assertEqual([card.text for card in self.pet.bubbles], ['26', '27', '28', '29'])
        self.pet.set_scale_percent(240)
        self.pet.set_scale_percent(120)
        self.assertEqual([card.text for card in self.pet.bubbles], ['26', '27', '28', '29'])

    def test_range_and_scale_preserve_a_manually_chosen_head_position(self):
        self.fixed.click()
        self.drag(self.body_point(), QPoint(-100, -110))
        image = self.pet.character.image_rect()
        original = self.pet.character.mapToGlobal(QPoint(image.center().x(), image.top()))
        self.pet.set_scale_percent(120)
        self.pet.set_display_percent(70)
        self.pet.set_reply_text(1, '重绘时位置保持稳定')
        QTest.qWait(40)
        image = self.pet.character.image_rect()
        current = self.pet.character.mapToGlobal(QPoint(image.center().x(), image.top()))
        self.assertEqual(current, original)

    def test_drag_moves_bubbles_and_character_together(self):
        self.pet.add_transcript('一起移动')
        QTest.qWait(40)
        card = self.pet.bubbles[-1]
        character_before = self.pet.character.mapToGlobal(QPoint())
        bubble_before = card.mapToGlobal(QPoint())
        self.fixed.click()
        self.drag(self.body_point(), QPoint(-30, -45))
        self.assertEqual(self.pet.character.mapToGlobal(QPoint()) - character_before, QPoint(-30, -45))
        self.assertEqual(card.mapToGlobal(QPoint()) - bubble_before, QPoint(-30, -45))

    def test_blank_area_does_not_drag_the_pet(self):
        self.fixed.click()
        position = self.pet.pos()
        self.drag(QPoint(10, 10), QPoint(-30, -40))
        self.assertEqual(self.pet.pos(), position)

    def test_top_toggle_preserves_free_position_and_hidden_state(self):
        self.fixed.click()
        self.drag(self.body_point(), QPoint(-25, -65))
        chosen = self.pet.pos()
        for enabled in (False, True):
            self.top.setChecked(enabled)
            self.assertTrue(self.pet.isVisible())
            self.assertEqual(self.pet.pos(), chosen)
            self.assertEqual(self.pet.windowType(), Qt.WindowType.Tool)
        self.hide.click()
        self.top.setChecked(False)
        self.assertFalse(self.pet.isVisible(), '隐藏时调整置顶不能重新显示角色')
        self.hide.click()
        self.assertEqual(self.pet.pos(), chosen)
        self.assertFalse(bool(self.pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))

    def test_direct_window_changes_are_reflected_in_controls(self):
        self.pet.hide()
        self.assertIn('已隐藏', self.status.text())
        self.assertEqual(self.hide.text(), '显示角色')
        self.pet.show()
        self.pet.set_stays_on_top(False)
        self.pet.set_position_fixed(False)
        self.assertIn('已显示', self.status.text())
        self.assertFalse(self.top.isChecked())
        self.assertFalse(self.fixed.isChecked())

    def test_escape_hides_and_showing_again_still_accepts_replies(self):
        QTest.keyClick(self.pet, Qt.Key.Key_Escape)
        self.assertFalse(self.pet.isVisible())
        self.assertIn('已隐藏', self.status.text())
        self.hide.click()
        self.pet.set_reply_text(1, '再次显示后仍能聊天')
        QTest.qWait(40)
        self.assertTrue(self.pet.isVisible())
        self.assertEqual(self.pet.bubbles[-1].text, '再次显示后仍能聊天')
        self.pet.shutdown()
        self.assertTrue(self.pet.stop_console.is_set(), '关闭整个程序时仍须真正清理立绘')


if __name__ == '__main__':
    unittest.main()
