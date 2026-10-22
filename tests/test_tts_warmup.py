"""Run the actual startup warmup function without importing/loading inference models."""
import ast
from contextlib import closing
import json
from pathlib import Path
from types import SimpleNamespace
import time
import traceback
import unittest
from unittest.mock import Mock, patch

import numpy as np


class WarmupTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'services/gpt_sovits/api_v2.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'warmup_tts']
        namespace = dict(json=json, time=time, traceback=traceback, closing=closing, np=np)
        exec(compile(tree, str(source), 'exec'), namespace)
        self.warmup = namespace['warmup_tts']

    def test_disabled_warmup_does_not_synthesize(self):
        pipeline = SimpleNamespace(run=Mock())
        self.assertIsNone(self.warmup(pipeline, '0'))
        self.assertIsNone(self.warmup(pipeline, None))
        pipeline.run.assert_not_called()

    def test_warmup_consumes_and_closes_generator(self):
        closed = []
        def run(request):
            self.assertEqual(request, {'text': '固定日文'})
            try:
                yield 32000, np.ones(640, dtype=np.int16)
                yield 32000, np.ones(640, dtype=np.int16)
            finally:
                closed.append(True)
        result = self.warmup(SimpleNamespace(run=run), json.dumps({'text': '固定日文'}))
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(closed, [True])

    def test_failed_warmup_is_reported_and_next_request_can_recover(self):
        calls = []
        def run(request):
            calls.append(request)
            if len(calls) == 1:
                raise RuntimeError('first inference failed')
            yield 32000, np.ones(640, dtype=np.int16)
        pipeline = SimpleNamespace(run=run)
        with patch.object(traceback, 'print_exc'):
            self.assertEqual(self.warmup(pipeline, '{}')['status'], 'failed')
        self.assertEqual(self.warmup(pipeline, '{}')['status'], 'ready')

    def test_silent_error_audio_is_not_reported_as_ready(self):
        def run(_):
            yield 32000, np.zeros(640, dtype=np.int16)
        with patch.object(traceback, 'print_exc'):
            self.assertEqual(self.warmup(SimpleNamespace(run=run), '{}')['status'], 'failed')
