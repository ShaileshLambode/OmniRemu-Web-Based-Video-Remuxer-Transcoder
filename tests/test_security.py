import io
import json
import unittest
from unittest.mock import Mock
from server import OmniRequestHandler, SESSION_TOKEN

class TestSecurity(unittest.TestCase):
    def setUp(self):
        self.handler = OmniRequestHandler.__new__(OmniRequestHandler)
        self.handler.server = Mock(server_port=5050)
        self.handler.send_response = Mock()
        self.handler.send_header = Mock()
        self.handler.end_headers = Mock()
        self.handler.wfile = io.BytesIO()

    def test_is_trusted_host(self):
        # Local loopback hosts
        for host in ["localhost:5050", "127.0.0.1:5050", "[::1]:5050", "localhost", "127.0.0.1", "[::1]"]:
            self.handler.headers = {"Host": host}
            self.assertTrue(self.handler.is_trusted_host(), f"Expected {host} to be trusted")

        # Untrusted external hosts
        for host in ["evil.com:5050", "attacker.net", "192.168.1.100:5050", "example.org", "", None]:
            self.handler.headers = {"Host": host} if host is not None else {}
            self.assertFalse(self.handler.is_trusted_host(), f"Expected {host} to be untrusted")

    def test_is_trusted_origin(self):
        # Valid localhost origin matching port
        self.handler.headers = {"Host": "localhost:5050", "Origin": "http://localhost:5050"}
        self.assertTrue(self.handler.is_trusted_origin())

        self.handler.headers = {"Host": "127.0.0.1:5050", "Origin": "http://127.0.0.1:5050"}
        self.assertTrue(self.handler.is_trusted_origin())

        self.handler.headers = {"Host": "[::1]:5050", "Origin": "http://[::1]:5050"}
        self.assertTrue(self.handler.is_trusted_origin())

        # Direct navigation without Origin header
        self.handler.headers = {"Host": "localhost:5050"}
        self.assertTrue(self.handler.is_trusted_origin())

        # Untrusted origins
        self.handler.headers = {"Host": "localhost:5050", "Origin": "http://evil.com"}
        self.assertFalse(self.handler.is_trusted_origin())

        # Port mismatch attack (DNS rebinding / port cross-talk)
        self.handler.headers = {"Host": "localhost:5050", "Origin": "http://localhost:8080"}
        self.assertFalse(self.handler.is_trusted_origin())

        # Scheme or host manipulation
        self.handler.headers = {"Host": "localhost:5050", "Origin": "http://evil-localhost:5050"}
        self.assertFalse(self.handler.is_trusted_origin())

    def test_validate_session_token(self):
        # Valid token
        self.handler.headers = {"X-Omni-Token": SESSION_TOKEN}
        self.assertTrue(self.handler.validate_session_token())

        # Invalid token
        self.handler.headers = {"X-Omni-Token": "bad_hex_token_1234567890"}
        self.assertFalse(self.handler.validate_session_token())

        # Missing token
        self.handler.headers = {}
        self.assertFalse(self.handler.validate_session_token())

    def test_get_endpoints_reject_untrusted_origin(self):
        endpoints = [
            "/api/status",
            "/api/local-files",
            "/api/jobs/test_id",
            "/api/thumbnail/sample.jpg",
            "/api/preview/sample.mp4",
            "/api/download/sample.mp4"
        ]
        for ep in endpoints:
            self.handler.path = ep
            self.handler.headers = {
                "Host": "localhost:5050",
                "Origin": "http://evil-site.com"
            }
            self.handler.wfile = io.BytesIO()
            self.handler.send_response.reset_mock()
            self.handler.do_GET()
            self.handler.send_response.assert_called_with(403)

    def test_post_rejects_untrusted_origin(self):
        endpoints = ["/api/probe", "/api/convert", "/api/jobs/cancel", "/api/open-folder", "/api/shutdown", "/api/upload"]
        for ep in endpoints:
            self.handler.path = ep
            self.handler.headers = {
                "Host": "localhost:5050",
                "Origin": "http://malicious-site.com",
                "Content-Length": "2",
                "Content-Type": "application/json",
                "X-Omni-Token": SESSION_TOKEN
            }
            self.handler.rfile = io.BytesIO(b"{}")
            self.handler.send_response.reset_mock()
            self.handler.do_POST()
            self.handler.send_response.assert_called_with(403)

    def test_post_rejects_missing_token(self):
        endpoints = ["/api/probe", "/api/convert", "/api/jobs/cancel", "/api/open-folder", "/api/shutdown"]
        for ep in endpoints:
            self.handler.path = ep
            self.handler.headers = {
                "Host": "localhost:5050",
                "Origin": "http://localhost:5050",
                "Content-Length": "2",
                "Content-Type": "application/json"
            }
            self.handler.rfile = io.BytesIO(b"{}")
            self.handler.send_response.reset_mock()
            self.handler.do_POST()
            self.handler.send_response.assert_called_with(403)

    def test_open_folder_rejects_path_traversal(self):
        self.handler.path = "/api/open-folder"
        payload = json.dumps({"path": "../../windows/system32"}).encode("utf-8")
        self.handler.headers = {
            "Host": "localhost:5050",
            "Origin": "http://localhost:5050",
            "Content-Length": str(len(payload)),
            "Content-Type": "application/json",
            "X-Omni-Token": SESSION_TOKEN
        }
        self.handler.rfile = io.BytesIO(payload)
        self.handler.do_POST()
        self.handler.send_response.assert_called_with(400)

    def test_probe_rejects_path_traversal(self):
        self.handler.path = "/api/probe"
        payload = json.dumps({"path": "../../../boot.ini"}).encode("utf-8")
        self.handler.headers = {
            "Host": "localhost:5050",
            "Origin": "http://localhost:5050",
            "Content-Length": str(len(payload)),
            "Content-Type": "application/json",
            "X-Omni-Token": SESSION_TOKEN
        }
        self.handler.rfile = io.BytesIO(payload)
        self.handler.do_POST()
        self.handler.send_response.assert_called_with(400)

    def test_convert_rejects_path_traversal(self):
        self.handler.path = "/api/convert"
        payload = json.dumps({"path": r"\\10.0.0.1\share\exploit.mp4"}).encode("utf-8")
        self.handler.headers = {
            "Host": "localhost:5050",
            "Origin": "http://localhost:5050",
            "Content-Length": str(len(payload)),
            "Content-Type": "application/json",
            "X-Omni-Token": SESSION_TOKEN
        }
        self.handler.rfile = io.BytesIO(payload)
        self.handler.do_POST()
        self.handler.send_response.assert_called_with(400)

if __name__ == "__main__":
    unittest.main()
