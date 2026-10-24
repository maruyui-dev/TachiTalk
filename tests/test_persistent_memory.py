import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.core.history import ConversationHistory
from app.core.session_file import SessionFile


class PersistentMemoryTests(unittest.TestCase):
    def test_capacity_500_and_context_selection_do_not_delete_older_saved_turns(self):
        history = ConversationHistory()
        for number in range(501):
            history.append(str(number), 'reply-' + str(number), 500)
        self.assertEqual(history.count, 500)
        self.assertEqual(history.messages(500)[0]['content'], '1')
        self.assertEqual(len(history.messages(5)), 10)
        self.assertEqual(len(history.messages(500)), 1000)
        for bad in (501, -1, True, 1.2):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                history.messages(bad)

    def test_clear_during_generation_does_not_restore_the_old_reply(self):
        history = ConversationHistory()
        history.append('old', 'old reply', 20)
        revision = history.revision
        self.assertTrue(history.clear())
        history.append('in flight', 'from old context', 20, revision=revision)
        self.assertEqual(history.messages(20), [])

    def test_save_failure_is_diagnostic_and_preserves_last_disk_memory(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'conversation.dat'
            history = ConversationHistory(SessionFile(path))
            history.append('saved', 'reply', 20)
            before = path.read_bytes()
            with patch.object(SessionFile, 'write', side_effect=PermissionError('fixture')):
                history.append('pending', 'reply 2', 20)
                self.assertFalse(history.clear())
            self.assertEqual(path.read_bytes(), before)
            self.assertIn('保存失败', history.last_error)
            self.assertEqual(history.count, 2)
            self.assertEqual(ConversationHistory(SessionFile(path)).count, 1)

    def test_corrupt_file_is_preserved_and_recovery_memory_loads_on_restart(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'conversation.dat'
            path.write_bytes(b'broken fixture')
            history = ConversationHistory(SessionFile(path))
            history.append('new memory', 'reply', 20)
            self.assertEqual(path.read_bytes(), b'broken fixture')
            again = ConversationHistory(SessionFile(path))
            self.assertEqual(again.messages(20)[0]['content'], 'new memory')

    def test_real_dpapi_memory_and_437_round_ui_setting_survive_two_processes(self):
        with TemporaryDirectory() as temp:
            code = r'''
import json,sys
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from app.core.history import ConversationHistory
from app.core.session_file import SessionFile
from app.ui import control_panel
root=Path(sys.argv[1]); mode=sys.argv[2]
app=QApplication([])
with patch.object(control_panel,'DATA_ROOT',root), patch.object(control_panel,'RESOURCE_STATE',root/'library.json'), patch.object(control_panel,'RESOURCE_DIRECTORY',root/'assets'), patch.object(control_panel,'RESOURCE_BUBBLE_DIRECTORY',root/'bubbles'):
 panel=control_panel.load_window();control_panel.remember_session(panel)
 memory=ConversationHistory(SessionFile(root/'memory/conversation.dat'))
 panel.persona_controls.bind_history(memory)
 if mode=='write':
  panel.persona_controls.context.setCurrentIndex(panel.persona_controls.context.findData(437))
  memory.append('I prefer quiet bedtime stories','remembered fixture',437)
 print(json.dumps({'context':panel.persona_controls.profiles.snapshot().context_turns,'messages':memory.messages(437),'count':memory.count}),flush=True)
 panel.close();app.processEvents()
'''
            values = []
            for mode in ('write', 'read'):
                result = subprocess.run([sys.executable, '-B', '-c', code, temp, mode],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=45)
                self.assertEqual(result.returncode, 0, result.stderr[-2000:])
                values.append(json.loads(next(line for line in result.stdout.splitlines() if line.startswith('{'))))
            self.assertEqual(values[0], values[1])
            self.assertEqual(values[1]['context'], 437)
            self.assertEqual(values[1]['count'], 1)
            raw = (Path(temp) / 'memory/conversation.dat').read_bytes()
            self.assertNotIn(b'bedtime', raw)
            self.assertNotIn(b'remembered fixture', raw)
