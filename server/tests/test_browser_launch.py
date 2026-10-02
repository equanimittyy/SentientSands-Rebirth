import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from browser_launch import open_when_ready, wait_for_port


def closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BrowserLaunchTest(unittest.TestCase):
    def setUp(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]

    def tearDown(self):
        self.listener.close()

    def test_wait_returns_once_port_listens(self):
        self.assertTrue(wait_for_port("127.0.0.1", self.port, timeout=2))

    def test_wait_gives_up_after_timeout(self):
        self.assertFalse(wait_for_port("127.0.0.1", closed_port(), timeout=0.5))

    def test_opens_web_app_url_when_ready(self):
        opened = []
        open_when_ready("127.0.0.1", self.port, timeout=2, opener=opened.append)
        self.assertEqual(opened, [f"http://127.0.0.1:{self.port}/"])

    def test_opens_nothing_when_port_never_listens(self):
        opened = []
        open_when_ready("127.0.0.1", closed_port(), timeout=0.5, opener=opened.append)
        self.assertEqual(opened, [])


if __name__ == "__main__":
    unittest.main()
