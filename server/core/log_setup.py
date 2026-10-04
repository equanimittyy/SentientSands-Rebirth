"""The server's log files and the log level that the player sets.

server.log holds one record per line in the format that the plugin also writes to SentientSands_SDK.log,
so one tool can read both and merge them by time. llm.log holds each prompt and reply with its line
breaks. Its records are all DEBUG, so it stays empty unless the player sets the level to DEBUG.
"""

import logging
import logging.handlers
import os

LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARN": logging.WARNING, "ERROR": logging.ERROR}
DEFAULT_LEVEL = "INFO"
FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

llm_log = logging.getLogger("llm")
llm_log.propagate = False


class OneLineFormatter(logging.Formatter):
    # A traceback still follows on its own lines, because format() appends it after formatMessage()
    def formatMessage(self, record):
        return super().formatMessage(record).replace("\r", "").replace("\n", "\\n")


def parse_level(text):
    name = str(text).strip().upper()
    return name if name in LEVELS else DEFAULT_LEVEL


def set_level(text):
    level = LEVELS[parse_level(text)]
    logging.getLogger().setLevel(level)
    llm_log.setLevel(level)


def setup(log_dir):
    logging.addLevelName(logging.WARNING, "WARN")
    root = logging.getLogger()
    stream = logging.StreamHandler()
    stream.setFormatter(OneLineFormatter(FORMAT))
    root.addHandler(stream)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    set_level(DEFAULT_LEVEL)
    try:
        os.makedirs(log_dir, exist_ok=True)
        server = logging.handlers.RotatingFileHandler(os.path.join(log_dir, "server.log"), maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
        server.setFormatter(OneLineFormatter(FORMAT))
        root.addHandler(server)
        llm = logging.handlers.RotatingFileHandler(os.path.join(log_dir, "llm.log"), maxBytes=2 * 1024 * 1024, backupCount=1, encoding="utf-8")
        llm.setFormatter(logging.Formatter(FORMAT))
        llm_log.addHandler(llm)
    except OSError as e:
        logging.error(f"SYSTEM: Cannot open the log files in {log_dir}: {e}")
