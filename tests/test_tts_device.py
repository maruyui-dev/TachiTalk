"""设备选择必须验证实际CUDA运算，不能只看设备是否存在。"""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import tts_service_entry as entry


class DeviceSelectionTests(unittest.TestCase):
    def torch(self, available=True):
        return SimpleNamespace(cuda=SimpleNamespace(is_available=Mock(return_value=available),
            get_device_name=Mock(return_value='test GPU'), empty_cache=Mock()),
            __version__='2.7.1+cu128', version=SimpleNamespace(cuda='12.8'))

    def test_unavailable_cuda_selects_cpu_without_gpu_probe(self):
        torch = self.torch(False)
        with patch.object(entry, 'probe_cuda', create=True) as probe:
            result = entry.select_device(torch)
        self.assertEqual((result['device'], result['is_half']), ('cpu', False))
        probe.assert_not_called()

    def test_working_gpu_uses_half_precision(self):
        with patch.object(entry, 'probe_cuda', create=True) as probe:
            result = entry.select_device(self.torch())
        self.assertEqual((result['device'], result['is_half']), ('cuda', True))
        probe.assert_called_once()

    def test_nvrtc_failure_falls_back_to_cpu_and_reports_reason(self):
        failure = RuntimeError('kernel source dump\nnvrtc: error: invalid value for --gpu-architecture (-arch)')
        with patch.object(entry, 'probe_cuda', create=True, side_effect=failure):
            result = entry.select_device(self.torch())
        self.assertEqual((result['device'], result['is_half']), ('cpu', False))
        self.assertIn('gpu-architecture', result['reason'])
        self.assertLess(len(result['reason']), 500)

    def test_forced_cpu_never_initializes_cuda(self):
        torch = self.torch()
        result = entry.select_device(torch, force_cpu=True)
        self.assertEqual(result['device'], 'cpu')
        torch.cuda.is_available.assert_not_called()
