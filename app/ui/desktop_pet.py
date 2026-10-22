"""桌面立绘：显示范围、人物与气泡缩放、九宫格位置和鼠标拖动。"""
import logging

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QImageReader, QPixmap
from app.ui.pet.pet_window import PetWindow
from app.ui.bubble_display import ScaledBubbleCard


class DesktopPetWindow(PetWindow):
    display_changed = Signal()
    expression_changed = Signal(str)

    def __init__(self, catalog=None):
        self.position_fixed = True
        self._manual_position = None
        self._drag_offset = None
        self._shutting_down = False
        self._full_body = False
        self._refreshing = False
        self.scale_percent = 180
        self.display_percent = 50
        self.bubble_gap = PetWindow.GAP
        self.anchor = (2, 2)
        self._layout_anchor = self.anchor
        self.bubble_skins = {}
        super().__init__(catalog=catalog)
        self.setWindowTitle('TachiTalk')
        self.setWindowFlag(Qt.WindowType.Tool)
        self._full_body = True
        self._update_available_area(self._screen.availableGeometry())

    def apply_catalog(self, catalog):
        """先完整加载新图，再取消旧渐变；同名神态换图也立即刷新缓存。"""
        cache = {path: QPixmap.fromImage(QImageReader(str(path)).read()) for path in set(catalog.paths.values())}
        if any(image.isNull() for image in cache.values()):
            raise ValueError('立绘图片无法解码，请重新导入有效PNG')
        character = self.character
        character.transition.stop()
        character._switching = False
        character._pending_expression = None
        character._next_pixmap = None
        character.catalog = catalog
        character._pixmaps = {name: cache[path] for name, path in catalog.paths.items()}
        character.current_expression = catalog.normalize(character.current_expression)
        character._current_pixmap = character._pixmaps[character.current_expression]
        character.current_effect.setOpacity(1.0)
        character.next_effect.setOpacity(0.0)
        character.ui.petLableNext.clear()
        self._settle_animation()
        self._refresh_geometry()
        self.expression_changed.emit(character.current_expression)

    def set_bubble_skins(self, skins):
        self._settle_animation()
        self.bubble_skins = dict(skins)
        for card in self.bubbles:
            card.set_skin(self.bubble_skins[card.color])
        self._refresh_geometry()

    def preview_expression(self, expression):
        self.character.change_expression(expression)
        self.expression_changed.emit(self.character.catalog.normalize(expression))

    def play_expression(self, turn_id, expression):
        super().play_expression(turn_id, expression)
        if self._expression_turn == turn_id:
            self.expression_changed.emit(self.character.catalog.normalize(expression))

    def finish_expression(self, turn_id):
        super().finish_expression(turn_id)
        if self._expression_turn is None:
            self.expression_changed.emit(self.character.catalog.default)

    @property
    def scale_ratio(self):
        # 180%是现有桌宠外观的基准；人物和气泡共用此比例。
        return self.scale_percent / 180

    def _update_available_area(self, area):
        if not self._full_body:
            return super()._update_available_area(area)
        self._refresh_geometry()

    def _refresh_geometry(self):
        head = None
        if self._manual_position is not None:
            image = self.character.image_rect()
            head = self.character.mapToGlobal(QPoint(image.center().x(), image.top()))
        self._refreshing = True
        try:
            self.MARGIN = max(1, round(PetWindow.MARGIN * self.scale_ratio))
            self.STAGGER = round(PetWindow.STAGGER * self.scale_ratio)
            self.GAP = round(self.bubble_gap * self.scale_ratio)
            self._body_height = max(1, round(self.character.DESIGN_HEIGHT * self.scale_percent / 100
                                           * self.display_percent / 100))
            for card in self.bubbles:
                card.set_display_scale(self.scale_ratio, self._text_width())
            self._headroom = self._required_headroom()
            self.resize(round(480 * self.scale_ratio), self._headroom + self._body_height + 2 * self.MARGIN)
            self._layout_children()
        finally:
            self._refreshing = False
        if head is not None:
            image = self.character.image_rect()
            local_head = self.character.pos() + QPoint(image.center().x(), image.top())
            self._manual_position = head - local_head
        self._anchor_to_desktop()

    def set_scale_percent(self, value):
        if not 60 <= value <= 240:
            raise ValueError('人物大小必须在60%到240%之间')
        if value != self.scale_percent:
            self._settle_animation()
            self.scale_percent = value
            self._refresh_geometry()
            self.display_changed.emit()

    def set_display_percent(self, value):
        if not 10 <= value <= 100:
            raise ValueError('显示范围必须在10%到100%之间')
        if value != self.display_percent:
            self._settle_animation()
            self.display_percent = value
            self._refresh_geometry()
            self.display_changed.emit()

    def set_anchor(self, row, column):
        if row not in range(3) or column not in range(3):
            raise ValueError('九宫格的行列必须在0到2之间')
        self._settle_animation()
        self.anchor = (row, column)
        self._layout_anchor = self.anchor
        self._manual_position = None
        self._refresh_geometry()
        self.display_changed.emit()

    def restore_manual_position(self, x, y, layout_anchor):
        """载入拖动后的位置；屏幕变动导致整个窗口在屏幕外时回到可用区域。"""
        self.set_anchor(*layout_anchor)
        point = QPoint(x, y)
        area = self._screen.availableGeometry()
        if not self.rect().translated(point).intersects(area):
            point = area.topLeft()
        self.anchor = None
        self._manual_position = point
        self._anchor_to_desktop()
        self.display_changed.emit()

    def set_max_bubbles(self, value):
        if not 1 <= value <= 10:
            raise ValueError('最多显示必须在1到10条之间')
        if value != self.MAX_BUBBLES:
            self._settle_animation()
            self.MAX_BUBBLES = value
            while len(self.bubbles) > value:
                self._remove_oldest_bubble()
            self._refresh_geometry()
            self.display_changed.emit()

    def set_bubble_gap(self, value):
        if not 0 <= value <= 100:
            raise ValueError('气泡间距必须在0到100像素之间')
        if value != self.bubble_gap:
            self._settle_animation()
            self.bubble_gap = value
            self._refresh_geometry()
            self.display_changed.emit()

    def _remove_oldest_bubble(self):
        oldest = self.bubbles.pop(0)
        if oldest is self._reply_card:
            self._reply_card = None
        oldest.hide()
        oldest.deleteLater()

    def _required_headroom(self):
        stack = sum(card.visible_rect.height() for card in self.bubbles)
        stack += max(0, len(self.bubbles) - 1) * self.GAP
        return max(round(700 * self.scale_ratio), stack + self.MARGIN)

    def _settle_animation(self):
        if self._animation_group is not None:
            self._animation_group.stop()
            self._finish_animation()
        for card in self.bubbles:
            card.fade_effect.setOpacity(1.0)

    def _text_width(self):
        if not self._full_body:
            return super()._text_width()
        return max(1, round(280 * self.scale_ratio))

    def _layout_children(self):
        if not self._full_body:
            return super()._layout_children()
        # 只改变显示切片，原始全身素材始终保留，切回100%可立即恢复全身。
        self.character.VISIBLE_FRACTION = self.display_percent / 100
        self.character.set_display_height(self._body_height)
        image = self.character.image_rect()
        row, column = self._layout_anchor
        left = (self.MARGIN, (self.width() - image.width()) // 2,
                self.width() - image.width() - self.MARGIN)[column]
        self.character.move(left - image.left(), self.MARGIN if row == 0 else self._headroom)
        self.bubble_area.setGeometry(self.rect())
        for card in self.bubbles:
            card.set_display_scale(self.scale_ratio, self._text_width())
        if not self._refreshing and self._headroom != self._required_headroom():
            # 译文变长也可能使气泡列变高，扩展父窗口而不改变人物的位置。
            self._refresh_geometry()
            return
        for card, position in self._bubble_positions():
            card.move(position)

    def _bubble_positions(self):
        positions = super()._bubble_positions()
        if self._full_body and self._layout_anchor[0] == 0:
            # 顶部定位时把气泡放到人物下方，避免整个气泡列落到屏幕外。
            top = self.character.geometry().bottom() + self.HEAD_GAP + 1
            below = []
            for card, position in positions:
                below.append((card, QPoint(position.x(), top - card.visible_rect.top())))
                top += card.visible_rect.height() + self.GAP
            return below
        return positions

    def _anchor_to_desktop(self):
        if self._refreshing:
            return
        if self._manual_position is not None:
            self.move(self._manual_position)
        elif self._full_body:
            area = self._screen.availableGeometry()
            body = self.character.image_rect().translated(self.character.pos())
            row, column = self.anchor
            x = (area.left() + self.MARGIN, area.center().x() - body.width() // 2,
                 area.right() - self.MARGIN - body.width() + 1)[column]
            y = (area.top() + self.MARGIN, area.center().y() - body.height() // 2,
                 area.bottom() - self.MARGIN - body.height() + 1)[row]
            self.move(QPoint(x, y) - body.topLeft())
        else:
            super()._anchor_to_desktop()

    def _show_next_message(self):
        if self._closing or self._animating or not self._pending_messages:
            return
        color, text, reply_turn = self._pending_messages.popleft()
        card = ScaledBubbleCard(color, text, self.bubble_area, self._text_width(), self.scale_ratio)
        if color in self.bubble_skins:
            card.set_skin(self.bubble_skins[color])
        while len(self.bubbles) >= self.MAX_BUBBLES:
            self._remove_oldest_bubble()
        self.bubbles.append(card)
        if reply_turn is not None and reply_turn == self._reply_turn:
            self._reply_card = card
        if self._headroom != self._required_headroom():
            positions = {bubble: bubble.mapToGlobal(QPoint()) for bubble in self.bubbles if bubble is not card}
            self._refresh_geometry()
            for bubble, position in positions.items():
                bubble.move(self.bubble_area.mapFromGlobal(position))
        group = QParallelAnimationGroup(self)
        for bubble, target in self._bubble_positions():
            if bubble is card:
                bubble.move(target + QPoint(0, round(20 * self.scale_ratio)))
                bubble.fade_effect.setOpacity(0.0)
            movement = QPropertyAnimation(bubble, b'pos')
            movement.setDuration(self.ANIMATION_MS)
            movement.setStartValue(bubble.pos())
            movement.setEndValue(target)
            movement.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(movement)
        fade = QPropertyAnimation(card.fade_effect, b'opacity')
        fade.setDuration(self.ANIMATION_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        group.addAnimation(fade)
        self._animation_group = group
        self._animating = True
        group.finished.connect(self._finish_animation)
        card.show()
        group.start()

    def set_stays_on_top(self, enabled):
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == enabled:
            return
        # 修改窗口标志会隐藏窗口，必须保留原来的位置及显示状态。
        visible, position = self.isVisible(), self.pos()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.move(position)
        if visible:
            self.show()
        self.display_changed.emit()

    def set_position_fixed(self, enabled):
        if self.position_fixed == enabled:
            return
        self.position_fixed = enabled
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.ArrowCursor if enabled else Qt.CursorShape.OpenHandCursor)
        self.display_changed.emit()

    def mousePressEvent(self, event):
        body = self.character.image_rect().translated(self.character.pos())
        if (not self.position_fixed and event.button() == Qt.MouseButton.LeftButton
                and body.contains(event.position().toPoint())):
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            # 用屏幕坐标计算，避免窗口移动后局部坐标改变而来回抖动。
            self._manual_position = event.globalPosition().toPoint() - self._drag_offset
            self.anchor = None
            self.move(self._manual_position)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._stop_drag()
            self.display_changed.emit()
            logging.getLogger('tachitalk.ui').info('角色位置：%s, %s', self.x(), self.y())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _stop_drag(self):
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.ArrowCursor if self.position_fixed else Qt.CursorShape.OpenHandCursor)

    def showEvent(self, event):
        super().showEvent(event)
        self.display_changed.emit()

    def hideEvent(self, event):
        self._stop_drag()
        super().hideEvent(event)
        self.display_changed.emit()

    def closeEvent(self, event):
        if self._shutting_down:
            super().closeEvent(event)
        else:
            # 单独关闭立绘只是收起，控制面板仍可再次显示它。
            self.hide()
            event.ignore()

    def shutdown(self):
        self._shutting_down = True
        self.close()

