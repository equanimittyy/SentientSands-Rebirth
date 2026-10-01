"""Rejects requests that a web page in the player's browser sends to the local server.

A page on any site can POST to 127.0.0.1 without a CORS preflight, and DNS
rebinding lets it read the responses under its own host name. The plugin
(WinHTTP) and the debugger (requests) send no Origin header, so they pass.
"""

ALLOWED_HOSTS = {"127.0.0.1:5000", "localhost:5000"}
ALLOWED_ORIGINS = {f"http://{host}" for host in ALLOWED_HOSTS}


def is_request_allowed(host, origin):
    return host in ALLOWED_HOSTS and (origin is None or origin in ALLOWED_ORIGINS)
