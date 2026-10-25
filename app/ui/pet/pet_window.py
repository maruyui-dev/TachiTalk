"""组合半身人物和紧凑聊天气泡；固定在任务栏上方的右下角。"""
from collections import deque
import logging
from threading import Event

from PySide6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation,
    QTimer, Qt, Signal, Slot,
)
from PySide6.QtWidgets import QApplication, QWidget
from .bubble import BubbleCard
from .character import CharacterWidget


class PetWindow(QWidget):
    message_requested = Signal(str, str)  # 颜色、正文
    expression_requested = Signal(str)
    exit_requested = Signal()
    closing = Signal()
    MAX_BUBBLES = 4
    MAX_PENDING_MESSAGES = 8
    MARGIN = 12
    STAGGER = 48  # 粉色向左偏，蓝色向右偏；两者横向范围仍然交叠
    GAP = 4  # 两条气泡的实际可见边缘之间留4像素
    HEAD_GAP = 0  # 最下面气泡的可见底边贴住呆毛顶端
    ANIMATION_MS = 280

    def __init__(self, catalog=None):
        super().__init__()
        self.setWindowTitle("TachiTalk · 角色")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.stop_console = Event()
        self.bubbles = []  # 按时间排列：最旧的在前面
        self._pending_messages = deque(maxlen=self.MAX_PENDING_MESSAGES)
        self._reply_turn = None
        self._reply_card = None
        self._reply_part_key = None
        self._expression_turn = None
        self._animation_group = None
        self._animating = False
        self._closing = False
        self.character = CharacterWidget(self, catalog=catalog)
        self.bubble_area = QWidget(self)
        self.character.raise_()  # 人物最后绘制，透明气泡层跨到头顶时不遮掉人物
        for widget in (self.character, self.bubble_area):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._screen = QApplication.primaryScreen()
        area = self._screen.availableGeometry()
        self.resize(min(480, area.width()), min(1100, area.height() - 24))
        self._layout_children()
        self._anchor_to_desktop()
        self._screen.availableGeometryChanged.connect(self._update_available_area)
        self.message_requested.connect(self.add_message, Qt.ConnectionType.QueuedConnection)
        self.expression_requested.connect(
            self.character.change_expression, Qt.ConnectionType.QueuedConnection,
        )
        self.exit_requested.connect(self.close, Qt.ConnectionType.QueuedConnection)

    def _text_width(self):
        # 为左右错位和边框留空间，长句达到此宽度后换行。
        return max(60, min(280, self.width() - 2 * (self.MARGIN + self.STAGGER) - 52))

    def _layout_children(self):
        height = min(420, max(100, round(self.height() * 0.40)))
        self.character.set_display_height(height)
        self.character.move(
            self.width() - self.character.width(),
            self.height() - height,
        )
        # 气泡控件的透明外缘可伸到人物区，但可见底边仍定位在呆毛处。
        self.bubble_area.setGeometry(self.rect())
        for card in self.bubbles:
            card.set_max_text_width(self._text_width())
        for card, position in self._bubble_positions():
            card.move(position)

    def _anchor_to_desktop(self):
        area = self._screen.availableGeometry()
        self.move(area.right() - self.width() - self.MARGIN + 1,
                  area.bottom() - self.height() + 1)

    def _update_available_area(self, area):
        # 任务栏或屏幕可用区域变化时，重新适配并保持底边贴合。
        self.resize(min(480, area.width()), min(1100, area.height() - 24))
        self._anchor_to_desktop()

    def _bubble_positions(self):
        positions = []
        bottom = self.character.y() - self.HEAD_GAP
        center_x = self.character.x() + self.character.image_rect().center().x()
        # 从最新消息向上倒着摆：新消息永远最靠近人物。
        for card in reversed(self.bubbles):
            visible = card.visible_rect
            y = bottom - visible.bottom() - 1
            offset = -self.STAGGER if card.color == "pink" else self.STAGGER
            x = center_x - visible.center().x() + offset
            positions.append((card, QPoint(x, y)))
            bottom = y + visible.top() - self.GAP
        # 靠右时整列一起左移，保留粉蓝错位，而不是把两种颜色分别挤到同一处。
        overflow = max(
            (pos.x() + card.visible_rect.right() + 1 - (self.width() - self.MARGIN)
             for card, pos in positions), default=0,
        )
        shift = max(0, overflow)
        return [
            (card, QPoint(max(self.MARGIN - card.visible_rect.left(), pos.x() - shift), pos.y()))
            for card, pos in positions
        ]

    @Slot(str, str)
    def add_message(self, color, text):
        if self._closing:
            return
        if color not in BubbleCard.STYLES:
            raise ValueError(f"不支持的气泡颜色：{color}")
        if not text.strip():
            return
        self._queue_message(color, text)

    def _queue_message(self, color, text, reply_turn=None):
        if len(self._pending_messages) == self.MAX_PENDING_MESSAGES:
            logging.getLogger("tachitalk").warning("气泡待显示队列已满，丢弃最旧待显示消息")
        self._pending_messages.append((color, text, reply_turn))
        self._show_next_message()

    @Slot(str)
    def add_transcript(self, text):
        self.add_message("blue", text)

    @Slot(int, str)
    def set_reply_text(self, turn_id, text):
        """同轮译文原位补全，避免每个短句都挤出一个新粉色气泡。"""
        if self._closing or not text.strip():
            return
        if self._reply_turn is not None and turn_id < self._reply_turn:
            return
        if self._reply_turn != turn_id:
            self._reply_turn = turn_id
            self._reply_card = None
        if self._reply_card is not None and self._reply_card in self.bubbles:
            self._reply_card.set_message(text)
            if self._animation_group is not None:
                self._animation_group.stop()
                self._finish_animation()
            self._layout_children()
            for card in self.bubbles:
                card.fade_effect.setOpacity(1.0)
            return
        for index, (color, _, pending_turn) in enumerate(self._pending_messages):
            if pending_turn == turn_id:
                self._pending_messages[index] = (color, text, turn_id)
                return
        self._queue_message("pink", text, turn_id)

    @Slot(int, str)
    def play_expression(self, turn_id, expression):
        if self._closing:
            return
        if self._expression_turn is not None and turn_id < self._expression_turn:
            return
        self._expression_turn = turn_id
        self.character.change_expression(expression)

    @Slot(int, int, str)
    def set_reply_part(self, turn_id, part_id, text):
        """Each semantic message gets a bubble; token updates stay in that bubble."""
        if self._closing or not text.strip() or (self._reply_turn is not None and turn_id < self._reply_turn):
            return
        key = (turn_id, part_id)
        if self._reply_part_key != key:
            self._reply_part_key = key
            self._reply_turn = turn_id
            self._reply_card = None
        if self._reply_card is not None and self._reply_card in self.bubbles:
            self._reply_card.set_message(text)
            self._layout_children()
            return
        for index, (color, _, pending_key) in enumerate(self._pending_messages):
            if pending_key == key:
                self._pending_messages[index] = (color, text, key)
                return
        self._queue_message('pink', text, key)

    @Slot(int)
    def finish_expression(self, turn_id):
        if not self._closing and self._expression_turn == turn_id:
            self._expression_turn = None
            self.character.change_expression(self.character.catalog.default)

    def _show_next_message(self):
        if self._closing or self._animating or not self._pending_messages:
            return
        color, text, reply_turn = self._pending_messages.popleft()
        card = BubbleCard(color, text, self.bubble_area, self._text_width())
        # 先移除旧消息，再显示新消息，动画中也最多四条。
        if len(self.bubbles) == self.MAX_BUBBLES:
            oldest = self.bubbles.pop(0)
            if oldest is self._reply_card:
                self._reply_card = None
            oldest.hide()
            oldest.deleteLater()
        self.bubbles.append(card)
        if reply_turn is not None and reply_turn in (self._reply_turn, self._reply_part_key):
            self._reply_card = card
        group = QParallelAnimationGroup(self)
        for bubble, target in self._bubble_positions():
            if bubble is card:
                bubble.move(target + QPoint(0, 20))
                bubble.fade_effect.setOpacity(0.0)
            movement = QPropertyAnimation(bubble, b"pos")
            movement.setDuration(self.ANIMATION_MS)
            movement.setStartValue(bubble.pos())
            movement.setEndValue(target)
            movement.setEasingCurve(QEasingCurve.Type.OutCubic)
            group.addAnimation(movement)
        fade = QPropertyAnimation(card.fade_effect, b"opacity")
        fade.setDuration(self.ANIMATION_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        group.addAnimation(fade)
        self._animation_group = group  # 保存引用，避免动画提前被回收
        self._animating = True
        group.finished.connect(self._finish_animation)
        card.show()
        group.start()

    def _finish_animation(self):
        group = self._animation_group
        self._animation_group = None
        self._animating = False
        if group is not None:
            group.deleteLater()
        QTimer.singleShot(0, self._show_next_message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "character"):
            return
        if self._animation_group is not None:
            self._animation_group.stop()
            self._finish_animation()
        self._layout_children()
        for card in self.bubbles:
            card.fade_effect.setOpacity(1.0)
        self._anchor_to_desktop()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._closing:
            super().closeEvent(event)
            return
        self._closing = True
        self.stop_console.set()
        self._pending_messages.clear()
        if self._animation_group is not None:
            self._animation_group.stop()
        self.character.transition.stop()
        self.closing.emit()
        super().closeEvent(event)
