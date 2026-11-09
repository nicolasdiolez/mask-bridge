"""Tests for the ONNX Runtime configuration helpers in inference_engine.py.

These guard a decision that is easy to undo by reflex: CoreML is OFF on purpose
(it refuses RF-DETR's rank-6 decoder tensors and measured 1.8x slower), and the
intra-op pool is pinned to the performance cores. No ONNX model is loaded here.
"""
import os
import sys

import onnxruntime as ort
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inference_engine import _intra_op_threads, _providers, _session_options


class TestProviders:
    def test_cpu_only_by_default(self, monkeypatch):
        """The shipped default must never reach for CoreML."""
        monkeypatch.delenv('MASKBRIDGE_ORT_PROVIDERS', raising=False)
        assert _providers() == ['CPUExecutionProvider']

    def test_env_var_reenables_coreml_when_available(self, monkeypatch):
        """The field-test escape hatch works without a rebuild."""
        monkeypatch.setenv('MASKBRIDGE_ORT_PROVIDERS', 'coreml')
        providers = _providers()
        if 'CoreMLExecutionProvider' in ort.get_available_providers():
            assert providers[0] == 'CoreMLExecutionProvider'
            assert 'CPUExecutionProvider' in providers
        else:
            # Windows / Linux: nothing to enable, must still be usable
            assert providers == ['CPUExecutionProvider']

    def test_env_var_is_case_and_space_insensitive(self, monkeypatch):
        monkeypatch.setenv('MASKBRIDGE_ORT_PROVIDERS', '  CoreML \n')
        expected = 'CoreMLExecutionProvider' in ort.get_available_providers()
        assert ('CoreMLExecutionProvider' in _providers()) is expected

    @pytest.mark.parametrize('value', ['', 'cuda', 'cpu', 'yes', 'CoreMLExecutionProvider'])
    def test_unknown_values_stay_on_cpu(self, monkeypatch, value):
        """Only the exact opt-in switches providers; anything else is CPU."""
        monkeypatch.setenv('MASKBRIDGE_ORT_PROVIDERS', value)
        assert _providers() == ['CPUExecutionProvider']


class TestIntraOpThreads:
    def test_between_one_and_the_total_core_count(self):
        """Performance cores are a subset: more than the total means a bad read."""
        threads = _intra_op_threads()
        assert isinstance(threads, int)
        assert 1 <= threads <= (os.cpu_count() or 4)

    @pytest.mark.skipif(sys.platform != 'darwin', reason='Apple Silicon core split')
    def test_apple_silicon_excludes_efficiency_cores(self):
        """On a machine with efficiency cores, pinning must drop them.

        Skipped on an Intel Mac, where perflevel0 is absent and the fallback to
        os.cpu_count() is the intended answer.
        """
        import subprocess
        probe = subprocess.run(['sysctl', '-n', 'hw.perflevel1.logicalcpu'],
                               capture_output=True, text=True)
        if probe.returncode != 0 or not probe.stdout.strip():
            pytest.skip('no efficiency cores on this Mac')
        efficiency = int(probe.stdout.strip())
        assert _intra_op_threads() == (os.cpu_count() or 0) - efficiency


class TestSessionOptions:
    def test_carries_optimization_and_pinning(self):
        opts = _session_options()
        assert opts.graph_optimization_level == ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        assert opts.intra_op_num_threads == _intra_op_threads()

    def test_returns_a_fresh_object_each_call(self):
        """Two models load concurrently; sharing one options object is a trap."""
        assert _session_options() is not _session_options()
