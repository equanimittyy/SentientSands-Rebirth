import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from browser_launch import PanelTabs, open_when_ready, wait_for_port


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
        open_when_ready("127.0.0.1", self.port, PanelTabs(), timeout=2, grace=0, opener=opened.append)
        self.assertEqual(opened, [f"http://127.0.0.1:{self.port}/"])

    def test_opens_nothing_when_port_never_listens(self):
        opened = []
        with self.assertLogs(level="WARNING"):
            open_when_ready("127.0.0.1", closed_port(), PanelTabs(), timeout=0.5, grace=0, opener=opened.append)
        self.assertEqual(opened, [])

    def test_opens_nothing_while_a_tab_is_open(self):
        tabs = PanelTabs()
        stream = tabs.stream(heartbeat=0)
        next(stream)
        opened = []
        open_when_ready("127.0.0.1", self.port, tabs, timeout=2, grace=0, opener=opened.append)
        self.assertEqual(opened, [])
        stream.close()


class PanelTabsTest(unittest.TestCase):
    def test_tab_is_open_while_its_stream_runs(self):
        tabs = PanelTabs()
        stream = tabs.stream(heartbeat=0)
        self.assertTrue(next(stream).startswith("retry: "))
        self.assertTrue(tabs.is_open())
        next(stream)
        self.assertTrue(tabs.is_open())
        stream.close()
        self.assertFalse(tabs.is_open())

    def test_tab_stays_open_while_another_stream_runs(self):
        tabs = PanelTabs()
        first, second = tabs.stream(heartbeat=0), tabs.stream(heartbeat=0)
        next(first)
        next(second)
        first.close()
        self.assertTrue(tabs.is_open())
        second.close()
        self.assertFalse(tabs.is_open())


if __name__ == "__main__":
    unittest.main()
