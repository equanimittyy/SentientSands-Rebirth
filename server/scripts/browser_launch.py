"""Opens the web app in the default browser once the server accepts connections.

A browser that opens before the server listens shows a connection error page.
A program cannot switch the browser to an existing tab, so the server opens no
tab while a tab of the web app holds its presence stream open.
"""

import logging
import socket
import threading
import time
import webbrowser

RECONNECT_MS = 1000


class PanelTabs:
    def __init__(self):
        self._lock = threading.Lock()
        self._count = 0

    def is_open(self):
        with self._lock:
            return self._count > 0

    def stream(self, heartbeat=1.0):
        with self._lock:
            self._count += 1
        try:
            yield f"retry: {RECONNECT_MS}\n\n"
            while True:
                time.sleep(heartbeat)
                # A closed tab is found only when a write to it fails.
                yield ": heartbeat\n\n"
        finally:
            with self._lock:
                self._count -= 1


def wait_for_port(host, port, timeout, interval=0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=interval):
                return True
        except OSError:
            time.sleep(interval)
    return False


# A tab that was open before the server started retries every RECONNECT_MS, so it reconnects within the grace time.
def open_when_ready(host, port, tabs, timeout=30, grace=3, opener=webbrowser.open):
    url = f"http://{host}:{port}/"
    if not wait_for_port(host, port, timeout):
        logging.warning(f"SYSTEM: Port {port} did not accept connections within {timeout} s, so the web app was not opened.")
        return
    time.sleep(grace)
    if tabs.is_open():
        logging.info("SYSTEM: The web app is already open in a tab, so no new tab was opened.")
        return
    opener(url)
    logging.info(f"SYSTEM: Opened the web app at {url}")
