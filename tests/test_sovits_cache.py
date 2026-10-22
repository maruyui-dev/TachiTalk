"""不向桌宠venv安装torch；用原SV方法和轻量张量替身验证缓存失效。"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from contextlib import nullcontext


ROOT = Path(__file__).resolve().parents[1] / 'services/gpt_sovits/GPT_SoVITS'


class Tensor:
    def __init__(self):
        self._version = 0
        self.device, self.dtype = 'cuda:0', 'float16'

    def half(self):
        return self

    def __iter__(self):
        return iter([self])

    def unsqueeze(self, _):
        return self


class ReferenceCacheTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / 'sv.py').read_text(encoding='utf-8'))
        tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        namespace = {'torch': SimpleNamespace(no_grad=nullcontext, stack=lambda values: values),
                     'Kaldi': SimpleNamespace(fbank=lambda *args, **kwargs: object())}
        exec(compile(tree, str(ROOT / 'sv.py'), 'exec'), namespace)
        self.sv = namespace['SV'].__new__(namespace['SV'])
        self.sv.is_half = True
        self.sv.embedding_model = SimpleNamespace(forward3=Mock(side_effect=lambda _: object()))

    def test_same_reference_reuses_embedding_across_sentences(self):
        reference = Tensor()
        first = self.sv.compute_embedding3(reference)
        second = self.sv.compute_embedding3(reference)
        self.assertIs(first, second)
        self.assertEqual(self.sv.embedding_model.forward3.call_count, 1)

    def test_new_or_modified_reference_recomputes_embedding(self):
        reference = Tensor()
        first = self.sv.compute_embedding3(reference)
        reference._version += 1
        self.assertIsNot(first, self.sv.compute_embedding3(reference))
        self.sv.compute_embedding3(Tensor())
        self.assertEqual(self.sv.embedding_model.forward3.call_count, 3)

    def test_cache_holds_only_the_current_reference_and_tracks_model(self):
        first, second = Tensor(), Tensor()
        self.sv.compute_embedding3(first)
        self.sv.compute_embedding3(second)
        self.sv.compute_embedding3(first)
        self.assertEqual(self.sv.embedding_model.forward3.call_count, 3)
        self.sv.embedding_model = SimpleNamespace(forward3=Mock(return_value=object()))
        self.sv.compute_embedding3(first)
        self.sv.embedding_model.forward3.assert_called_once()

    def test_precision_change_invalidates_embedding(self):
        reference = Tensor()
        self.sv.compute_embedding3(reference)
        self.sv.is_half = False
        self.sv.compute_embedding3(reference)
        self.assertEqual(self.sv.embedding_model.forward3.call_count, 2)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / 'TTS_infer_pack/TTS.py').read_text(encoding='utf-8'))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'TTS')
        cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'empty_cache']
        tree.body = [cls]
        self.gc, self.cuda = Mock(), Mock()
        namespace = {'gc': self.gc, 'torch': SimpleNamespace(cuda=self.cuda)}
        exec(compile(tree, 'TTS.py', 'exec'), namespace)
        self.tts = namespace['TTS']()
        self.tts.configs = SimpleNamespace(device='cuda')

    def test_successful_requests_reuse_allocator_but_periodically_collect(self):
        for _ in range(15):
            self.tts.empty_cache(force=False)
        self.cuda.empty_cache.assert_not_called()
        self.assertEqual(self.gc.collect.call_count, 15)
        self.tts.empty_cache(force=False)
        self.cuda.empty_cache.assert_called_once()
        self.gc.collect.assert_called_with()

    def test_interrupt_error_or_model_change_can_force_full_cleanup(self):
        self.tts.empty_cache(force=False)
        self.tts.empty_cache()
        self.cuda.empty_cache.assert_called_once()
        self.gc.collect.assert_called_with()
        self.tts.empty_cache(force=False)
        self.cuda.empty_cache.assert_called_once()


if __name__ == '__main__':
    unittest.main()
