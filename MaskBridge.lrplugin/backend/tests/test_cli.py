"""Tests for CLI module."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from cli import (
    format_size,
    verify_model,
    MODELS,
    MODEL_MIN_SIZES,
    VERSION,
)


class TestFormatSize(unittest.TestCase):
    def test_units(self):
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(512), "512 B")
        self.assertEqual(format_size(2048), "2.0 KB")
        self.assertEqual(format_size(5 * 1024 * 1024), "5.0 MB")


class TestVerifyModel(unittest.TestCase):
    def test_missing_file(self):
        ok, msg = verify_model("/nonexistent/model.onnx", "model.onnx")
        self.assertFalse(ok)
        self.assertIn("NOT FOUND", msg)

    def test_model_registry(self):
        """MODELS dict should have corresponding min sizes."""
        for name in MODELS:
            self.assertIn(name, MODEL_MIN_SIZES,
                          f"Model {name} missing from MODEL_MIN_SIZES")
            self.assertGreater(MODEL_MIN_SIZES[name], 0)


class TestVersion(unittest.TestCase):
    def test_version_format(self):
        parts = VERSION.split(".")
        self.assertEqual(len(parts), 3)
        for part in parts:
            int(part)  # Should not raise

    def test_plugin_engine_and_verifiers_carry_the_same_version(self):
        """release.py refuses an engine whose version differs from the plugin."""
        import re
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        plugin = root / "MaskBridge.lrplugin"
        info = (plugin / "Info.lua").read_text(encoding="utf-8")
        major, minor, revision, display = re.search(
            r'VERSION = \{ major = (\d+), minor = (\d+), revision = (\d+), display = "([^"]+)" \}', info).groups()
        self.assertEqual(f"{major}.{minor}.{revision}", VERSION)
        self.assertEqual(display, VERSION)
        config = (plugin / "MaskBridgeConfig.lua").read_text(encoding="utf-8")
        self.assertIn(f'MaskBridgeConfig.VERSION = "{VERSION}"', config)
        for verifier in ("verify_macos.py", "verify_windows.py"):
            text = (root / "tools/release" / verifier).read_text(encoding="utf-8")
            self.assertIn(f"== '{VERSION}'", text, verifier)


if __name__ == "__main__":
    unittest.main()
