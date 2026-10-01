import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from request_guard import is_request_allowed


class IsRequestAllowedTest(unittest.TestCase):
    def test_allows_plugin_requests_without_origin(self):
        self.assertTrue(is_request_allowed("localhost:5000", None))
        self.assertTrue(is_request_allowed("127.0.0.1:5000", None))

    def test_allows_same_origin_browser_requests(self):
        self.assertTrue(is_request_allowed("127.0.0.1:5000", "http://127.0.0.1:5000"))
        self.assertTrue(is_request_allowed("localhost:5000", "http://localhost:5000"))

    def test_rejects_cross_site_origin(self):
        self.assertFalse(is_request_allowed("127.0.0.1:5000", "https://evil.example"))
        self.assertFalse(is_request_allowed("127.0.0.1:5000", "null"))
        self.assertFalse(is_request_allowed("localhost:5000", "http://localhost:3000"))

    def test_rejects_rebound_host(self):
        self.assertFalse(is_request_allowed("evil.example:5000", None))
        self.assertFalse(is_request_allowed("evil.example:5000", "http://evil.example:5000"))

    def test_rejects_missing_or_portless_host(self):
        self.assertFalse(is_request_allowed(None, None))
        self.assertFalse(is_request_allowed("localhost", None))


if __name__ == "__main__":
    unittest.main()
