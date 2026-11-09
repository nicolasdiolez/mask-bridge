"""tools/fetch_models.py must download exactly the models the engine verifies."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent.parent
sys.path.insert(0, str(BACKEND))

from cli import MODEL_MIN_SIZES, MODEL_SHA256  # noqa: E402


def load_fetch_models():
    spec = importlib.util.spec_from_file_location("fetch_models", ROOT / "tools" / "fetch_models.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFetchModels(unittest.TestCase):
    def setUp(self):
        self.fetch = load_fetch_models()

    def test_same_models_and_hashes_as_the_engine(self):
        self.assertEqual(set(self.fetch.MODELS), set(MODEL_SHA256))
        for name, (sha, size) in self.fetch.MODELS.items():
            self.assertEqual(sha, MODEL_SHA256[name], name)
            self.assertGreaterEqual(size, MODEL_MIN_SIZES[name], name)

    def test_models_land_where_the_engine_looks(self):
        self.assertEqual(self.fetch.MODELS_DIR, BACKEND / "models")

    def test_bad_download_is_removed_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "served.onnx"
            source.write_bytes(b"not a model")
            dest = Path(tmp) / "out" / "model.onnx"
            dest.parent.mkdir()
            with self.assertRaises(RuntimeError):
                self.fetch.download(source.as_uri(), dest, "0" * 64, len(b"not a model"))
            self.assertFalse(dest.exists())
            self.assertEqual(os.listdir(dest.parent), [])

    def test_good_download_is_moved_into_place(self):
        import hashlib
        payload = b"model bytes"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "served.onnx"
            source.write_bytes(payload)
            dest = Path(tmp) / "out" / "model.onnx"
            dest.parent.mkdir()
            with mock.patch("builtins.print"):
                self.fetch.download(source.as_uri(), dest, hashlib.sha256(payload).hexdigest(), len(payload))
            self.assertEqual(dest.read_bytes(), payload)
            self.assertEqual(os.listdir(dest.parent), ["model.onnx"])


if __name__ == "__main__":
    unittest.main()
