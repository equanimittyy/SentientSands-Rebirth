import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from log_setup import OneLineFormatter, llm_log, parse_level, set_level, setup


class ParseLevelTest(unittest.TestCase):
    def test_accepts_the_four_levels_in_any_case(self):
        self.assertEqual(parse_level("debug"), "DEBUG")
        self.assertEqual(parse_level(" Warn "), "WARN")
        self.assertEqual(parse_level("ERROR"), "ERROR")

    def test_unknown_text_falls_back_to_info(self):
        self.assertEqual(parse_level("WARNING"), "INFO")
        self.assertEqual(parse_level(""), "INFO")
        self.assertEqual(parse_level(None), "INFO")


class OneLineFormatterTest(unittest.TestCase):
    def record(self, msg, exc_info=None):
        return logging.LogRecord("test", logging.INFO, __file__, 1, msg, None, exc_info)

    def test_message_line_breaks_are_escaped(self):
        text = OneLineFormatter("%(message)s").format(self.record("CHAT: first\r\nsecond"))
        self.assertEqual(text, "CHAT: first\\nsecond")

    def test_traceback_keeps_its_own_lines(self):
        try:
            raise ValueError("boom")
        except ValueError:
            text = OneLineFormatter("%(message)s").format(self.record("HTTP: failed", sys.exc_info()))
        lines = text.split("\n")
        self.assertEqual(lines[0], "HTTP: failed")
        self.assertEqual(lines[1], "Traceback (most recent call last):")


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = logging.getLogger()
        self.root_handlers = list(self.root.handlers)
        self.root_level = self.root.level
        self.root.handlers = []
        setup(self.folder.name)
        self.root.handlers = [h for h in self.root.handlers if isinstance(h, logging.FileHandler)]

    def tearDown(self):
        for logger in (self.root, llm_log):
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
        self.root.handlers = self.root_handlers
        self.root.setLevel(self.root_level)
        llm_log.setLevel(logging.NOTSET)
        logging.addLevelName(logging.WARNING, "WARNING")
        self.folder.cleanup()

    def read(self, name):
        for handler in self.root.handlers + llm_log.handlers:
            handler.flush()
        with open(os.path.join(self.folder.name, name), encoding="utf-8") as f:
            return f.read()

    def test_info_level_writes_one_line_records_without_debug(self):
        logging.debug("CHAT: hidden")
        logging.warning("CHAT: shown\nsame record")
        llm_log.debug("chat request:\nprompt")
        lines = self.read("server.log").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} - WARN - CHAT: shown\\nsame record$")
        self.assertEqual(self.read("llm.log"), "")

    def test_debug_level_fills_llm_log_with_line_breaks(self):
        set_level("DEBUG")
        logging.debug("CHAT: shown")
        llm_log.debug("chat request:\nprompt")
        self.assertIn(" - DEBUG - CHAT: shown", self.read("server.log"))
        self.assertIn(" - DEBUG - chat request:\nprompt\n", self.read("llm.log"))
        self.assertNotIn("chat request", self.read("server.log"))


if __name__ == "__main__":
    unittest.main()
