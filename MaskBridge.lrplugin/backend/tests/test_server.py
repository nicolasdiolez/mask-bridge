"""Tests for the HTTP server module."""
import json
import os
import sys
import threading
import unittest
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class _HTTPServerFixture:
    """Boots a real MaskBridge HTTP server for a test class.

    Deliberately NOT a TestCase: mixing it in gives each test class its own
    server without unittest re-collecting (and re-running) another class's tests.
    """

    TOKEN = "test-token-not-a-real-secret"

    @classmethod
    def setUpClass(cls):
        """Start the server in a background thread."""
        from http.server import ThreadingHTTPServer
        # Import handler but avoid loading models
        import server
        from server import MaskBridgeHandler

        # Stand in for the token the real entry points mint at startup.
        cls._saved_token = server._auth_token
        server._auth_token = cls.TOKEN

        # Listening from construction: requests queue until serve_forever runs.
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), MaskBridgeHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        import server
        server._auth_token = cls._saved_token

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path, headers=None):
        hdrs = {"X-MaskBridge-Token": self.TOKEN}
        hdrs.update(headers or {})
        req = urllib.request.Request(self._url(path), headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode()), resp.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read().decode()), e.code

    def _post(self, path, data=None, headers=None):
        body = json.dumps(data or {}).encode()
        hdrs = {"Content-Type": "application/json",
                "X-MaskBridge-Token": self.TOKEN}
        hdrs.update(headers or {})
        req = urllib.request.Request(
            self._url(path), data=body, headers=hdrs, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode()), resp.status
        except urllib.error.HTTPError as e:
            return json.loads(e.read().decode()), e.code


class TestServerEndpoints(_HTTPServerFixture, unittest.TestCase):
    """Integration tests for the MaskBridge HTTP server."""

    # --- Health ---
    def test_health_answers_get_and_post(self):
        for data, status in (self._get("/health"), self._post("/health")):
            self.assertEqual(status, 200)
            self.assertEqual(data["status"], "ok")
            self.assertIn("pid", data)

    def test_health_reports_the_engine_version(self):
        # The plugin replaces an engine of another release (8 November 2026:
        # a 1.1.1 engine answered a fresh 1.2.0 with "License required").
        import cli
        for data, status in (self._get("/health"), self._post("/health")):
            self.assertEqual(status, 200)
            self.assertEqual(data["version"], cli.VERSION)

    def test_unknown_endpoints_return_404(self):
        self.assertEqual(self._get("/nonexistent")[1], 404)
        self.assertEqual(self._post("/nonexistent")[1], 404)

    # --- Invalid JSON ---
    def test_invalid_json_returns_400(self):
        req = urllib.request.Request(
            self._url("/process"),
            data=b"not json",
            headers={"Content-Type": "application/json",
                     "X-MaskBridge-Token": self.TOKEN},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            self.fail("Expected 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            body = json.loads(e.read().decode())
            self.assertIn("Invalid JSON", body["error"])

    # --- Missing params ---
    def test_process_missing_params_returns_400(self):
        data, status = self._post("/process", {"image": "/tmp/test.jpg"})
        self.assertEqual(status, 400)
        self.assertIn("Missing required", data["error"])

    # --- Removed licensing endpoints ---
    def test_former_licence_endpoints_are_gone(self):
        for path in ("/validate-license", "/activate-license", "/deactivate-license"):
            data, status = self._post(path, {})
            self.assertEqual(status, 404, path)
            self.assertEqual(data["error"], "Unknown endpoint")

    # --- Process: no key, no network ---
    def test_process_needs_no_key(self):
        import tempfile
        from unittest.mock import MagicMock, patch
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as tmp:
            image = os.path.join(tmp, "photo.jpg")
            output = os.path.join(tmp, "photo.mask.png")
            cv2.imwrite(image, np.full((32, 48, 3), 128, dtype=np.uint8))
            engine = MagicMock()
            engine.process_image.side_effect = lambda **kw: (
                cv2.imwrite(kw["output_path"], np.zeros((32, 48), dtype=np.uint8)),
                {"detections": 1, "warnings": []})[1]
            with patch("server.get_or_load_engine", return_value=engine):
                data, status = self._post("/process", {
                    "image": image, "output": output,
                    "prompts": ["person"], "model_dir": tmp,
                })
        self.assertEqual(status, 200, data)
        self.assertEqual(data["status"], "success")
        engine.process_image.assert_called_once()

    # --- Matte endpoint (no model needed) ---
    def test_matte_missing_params_returns_400(self):
        data, status = self._post("/matte", {"input": "/tmp/render.jpg"})
        self.assertEqual(status, 400)
        self.assertIn("Missing required", data["error"])

    def test_matte_converts_render_to_grayscale_mask(self):
        import tempfile
        import numpy as np
        import cv2

        with tempfile.TemporaryDirectory() as tmp:
            # Synthetic matte render: black background, white subject square
            render = np.zeros((200, 200, 3), dtype=np.uint8)
            render[60:140, 60:140] = 255
            input_path = os.path.join(tmp, "render.jpg")
            output_path = os.path.join(tmp, "mask.png")
            cv2.imwrite(input_path, render)

            data, status = self._post("/matte", {
                "input": input_path,
                "output": output_path,
            })
            self.assertEqual(status, 200)
            self.assertEqual(data["status"], "success")

            mask = cv2.imread(output_path, cv2.IMREAD_GRAYSCALE)
            self.assertIsNotNone(mask)
            self.assertGreater(int(mask[100, 100]), 200)  # subject → white
            self.assertLess(int(mask[10, 10]), 50)        # background → black


class TestRequestAuthentication(_HTTPServerFixture, unittest.TestCase):
    """Localhost is not a trust boundary: other local processes and the user's
    own browser can reach this port. Only the Lightroom client may drive it."""

    def test_action_endpoint_refuses_without_token(self):
        data, status = self._post("/merge-alpha", {"rgb_path": "/tmp/a.png",
                                                   "mask_path": "/tmp/b.png",
                                                   "output_path": "/tmp/c.png"},
                                  headers={"X-MaskBridge-Token": ""})
        self.assertEqual(status, 401)
        self.assertEqual(data["error"], "Unauthorized")

    def test_action_endpoint_refuses_wrong_token(self):
        data, status = self._post("/matte", {"input": "/tmp/a.jpg",
                                             "output": "/tmp/b.png"},
                                  headers={"X-MaskBridge-Token": "guessed"})
        self.assertEqual(status, 401)

    def test_shutdown_refuses_without_token(self):
        """An <img src=...> drive-by must not be able to stop the engine."""
        data, status = self._get("/shutdown", headers={"X-MaskBridge-Token": ""})
        self.assertEqual(status, 401)
        # Still alive
        self.assertEqual(self._get("/health")[1], 200)

    def test_browser_origin_is_refused_even_on_exempt_health(self):
        data, status = self._get("/health", headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 401)

    def test_browser_origin_is_refused_even_with_valid_token(self):
        data, status = self._post("/process", {},
                                  headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 401)

    def test_health_stays_reachable_without_token(self):
        """The 'is the engine up?' path must never depend on token freshness."""
        data, status = self._get("/health", headers={"X-MaskBridge-Token": ""})
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")

    def test_authorized_request_still_works(self):
        data, status = self._post("/process", {})
        self.assertEqual(status, 400)  # missing params, but it got past auth
        self.assertIn("Missing required parameter", data["error"])


class TestDashboardWindowEndpoint(_HTTPServerFixture, unittest.TestCase):
    """POST /dashboard-window keeps the dashboard above Lightroom only."""

    def test_reports_what_was_attached(self):
        from unittest.mock import patch
        import server
        result = {"status": "ok", "found": 1, "attached": 1}
        with patch.object(server.dashboard_window, "attach_dashboard", return_value=result) as attach:
            data, status = self._post("/dashboard-window")
        self.assertEqual((status, data), (200, result))
        attach.assert_called_once_with()

    def test_requires_the_token(self):
        from unittest.mock import patch
        import server
        with patch.object(server.dashboard_window, "attach_dashboard") as attach:
            _, status = self._post("/dashboard-window", headers={"X-MaskBridge-Token": "wrong"})
        self.assertEqual(status, 401)
        attach.assert_not_called()

    def test_failure_is_reported_not_raised(self):
        from unittest.mock import patch
        import server
        with patch.object(server.dashboard_window, "attach_dashboard", side_effect=OSError("denied")):
            data, status = self._post("/dashboard-window")
        self.assertEqual(status, 500)
        self.assertEqual(data["status"], "error")


class TestBatchEndpoint(_HTTPServerFixture, unittest.TestCase):
    """Tests for the /batch endpoint path safety and manifest processing."""

    def test_batch_missing_manifest(self):
        data, status = self._post("/batch", {})
        self.assertEqual(status, 400)
        self.assertIn("Missing manifest", data["error"])

    def test_batch_sensitive_manifest_path_rejected(self):
        data, status = self._post("/batch", {
            "manifest": "/etc/shadow"
        })
        self.assertEqual(status, 400)
        self.assertIn("Invalid path", data["error"])

    def test_batch_rejects_sensitive_image_paths(self):
        import tempfile
        from unittest.mock import patch, MagicMock

        manifest_data = {
            "prompts": ["person"],
            "images": [
                {"input": "/etc/passwd", "output": os.path.join(tempfile.gettempdir(), "out1.png")},
                {"input": os.path.join(tempfile.gettempdir(), "in2.jpg"), "output": "/etc/sudoers"}
            ]
        }
        manifest_file = os.path.join(tempfile.gettempdir(), "test_batch_manifest.json")
        with open(manifest_file, "w") as f:
            json.dump(manifest_data, f)

        mock_engine = MagicMock()
        with patch("server.get_or_load_engine", return_value=mock_engine):
            data, status = self._post("/batch", {
                "manifest": manifest_file,
            })
            self.assertEqual(status, 400)
            self.assertIn("protected system directory", data.get("message", data.get("error", "")))
            # engine.process_image should NEVER have been called because both items were rejected
            mock_engine.process_image.assert_not_called()

        try:
            os.remove(manifest_file)
            result_file = manifest_file.replace('.json', '.result.json')
            if os.path.exists(result_file):
                os.remove(result_file)
        except OSError:
            pass


class TestStateCleanupOnExit(unittest.TestCase):
    """An exiting engine must not delete the state record of the engine that
    replaced it (a newer release sharing the same runtime folder)."""

    def _files(self, directory, pid):
        paths = [os.path.join(directory, name) for name in ('.server_port', '.server_token', '.server_state.json')]
        for path in paths[:2]:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('x')
        with open(paths[2], 'w', encoding='utf-8') as f:
            json.dump({'port': 9876, 'token': 't', 'pid': pid}, f)
        return paths

    def test_own_state_is_removed(self):
        import tempfile
        import server
        with tempfile.TemporaryDirectory() as d:
            port_file, token_file, state = self._files(d, os.getpid())
            server._remove_own_state(d, port_file, token_file)
            self.assertFalse(any(os.path.exists(p) for p in (port_file, token_file, state)))

    def test_state_of_a_replacing_engine_is_kept(self):
        import tempfile
        import server
        with tempfile.TemporaryDirectory() as d:
            port_file, token_file, state = self._files(d, os.getpid() + 1)
            server._remove_own_state(d, port_file, token_file)
            self.assertTrue(all(os.path.exists(p) for p in (port_file, token_file, state)))

    def test_missing_state_is_not_an_error(self):
        import tempfile
        import server
        with tempfile.TemporaryDirectory() as d:
            server._remove_own_state(d, os.path.join(d, '.server_port'), os.path.join(d, '.server_token'))


if __name__ == "__main__":
    unittest.main()
