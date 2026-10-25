"""Actual Qt messages preserve part boundaries and coalesce only same-part tokens."""
from pathlib import Path
import time
import unittest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app.ui.desktop import CaptionRelay, DesktopSignals, DesktopUI
from app.ui.desktop_pet import DesktopPetWindow
from app.ui.pet.expressions import ExpressionCatalog


class SegmentedBubbleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_twelve_fast_parts_reach_individual_real_bubbles_without_dropping(self):
        pet = DesktopPetWindow(ExpressionCatalog())
        pet.ANIMATION_MS = 40
        pet.show()
        self.addCleanup(pet.deleteLater)
        self.addCleanup(pet.shutdown)
        relay = CaptionRelay(pet)
        self.addCleanup(relay.close)
        delivered = []
        original = pet.set_reply_part
        def display(turn, part, text):
            delivered.append((turn, part, text))
            original(turn, part, text)
        pet.set_reply_part = display
        signals = DesktopSignals()
        signals.caption_part.connect(relay.offer_part)
        ui = DesktopUI(signals, 2)
        ui.begin_reply(1)
        for part in range(12):
            ui.caption(1, part, f'第{part + 1}条')
            ui.caption(1, part, f'第{part + 1}条完整消息。')
        deadline = time.monotonic() + 5
        while len(delivered) < 12 and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertEqual([p for _, p, _ in delivered], list(range(12)))
        self.assertTrue(all(text == f'第{part + 1}条完整消息。' for _, part, text in delivered))
        self.assertEqual(len(pet.bubbles), pet.MAX_BUBBLES)
        self.assertFalse(pet._pending_messages)
        self.assertEqual(len(ui.caption_parts), 12, 'All messages remain in the current turn')
        output = Path('work/install-progress-20261025/segmented-bubbles.png')
        output.parent.mkdir(parents=True, exist_ok=True)
        QTest.qWait(80)
        self.assertTrue(pet.grab().save(str(output)))
