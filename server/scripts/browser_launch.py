"""Opens the web app in the default browser once the server accepts connections.

A browser that opens before the server listens shows a connection error page.
"""

import logging
import socket
import time
import webbrowser


def wait_for_port(host, port, timeout, interval=0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=interval):
                return True
        except OSError:
            time.sleep(interval)
    return False


def open_when_ready(host, port, timeout=30, opener=webbrowser.open):
    url = f"http://{host}:{port}/"
    if wait_for_port(host, port, timeout):
        opener(url)
        logging.info(f"SYSTEM: Opened the web app at {url}")
    else:
        logging.warning(f"SYSTEM: Port {port} did not accept connections within {timeout} s, so the web app was not opened.")
