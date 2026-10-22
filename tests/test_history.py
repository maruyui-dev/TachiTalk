import unittest

from app.core.history import ConversationHistory


class HistoryTests(unittest.TestCase):
    def test_context_is_bounded_and_always_contains_complete_turn_pairs(self):
        history = ConversationHistory()
        for i in range(35):
            history.append(f'user-{i}', f'assistant-{i}', 20)
        messages = history.messages(20)
        self.assertEqual(len(messages), 40)
        self.assertEqual(messages[0], {'role': 'user', 'content': 'user-15'})
        self.assertEqual(messages[-1], {'role': 'assistant', 'content': 'assistant-34'})
        self.assertEqual([m['role'] for m in messages], ['user', 'assistant'] * 20)

    def test_shortening_context_discards_old_turns_and_never_resurrects_them(self):
        history = ConversationHistory()
        for i in range(20):
            history.append(f'user-{i}', f'assistant-{i}', 20)
        self.assertEqual(len(history.messages(5)), 10)
        self.assertEqual(len(history.messages(20)), 10)
        history.append('new-user', 'new-assistant', 5)
        self.assertEqual(history.messages(5)[0]['content'], 'user-16')

