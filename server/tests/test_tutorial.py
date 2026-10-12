import os
import re
import unittest
from html.parser import HTMLParser

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dashboard", "web")
INDEX = os.path.join(WEB, "index.html")
HELP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "plugin", "ui", "HelpWindow.cpp")


class TutorialPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = set()
        self.links = []
        self.files = []
        self.titles = []
        self.inside = False
        self.in_summary = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section":
            self.sections.add(attrs.get("id"))
            self.inside = attrs.get("id") == "tutorial"
        elif self.inside and tag == "a" and attrs.get("href", "").startswith("#"):
            self.links.append(attrs["href"][1:])
        elif self.inside and tag == "video":
            self.files += [attrs["src"], attrs["poster"]]
        elif self.inside and tag == "summary":
            self.in_summary = True
            self.titles.append("")

    def handle_endtag(self, tag):
        if tag == "section":
            self.inside = False
        elif tag == "summary":
            self.in_summary = False

    def handle_data(self, data):
        if self.in_summary:
            self.titles[-1] += data


class TutorialTest(unittest.TestCase):
    def setUp(self):
        self.parser = TutorialPage()
        with open(INDEX, encoding="utf-8") as f:
            self.parser.feed(f.read())

    def test_tab_links_name_a_page(self):
        self.assertTrue(self.parser.links)
        self.assertEqual([link for link in self.parser.links if link not in self.parser.sections], [])

    def test_videos_and_posters_exist(self):
        self.assertTrue(self.parser.files)
        missing = [path for path in self.parser.files if not os.path.isfile(os.path.join(WEB, path.removeprefix("/web/")))]
        self.assertEqual(missing, [])

    def test_each_help_topic_has_a_card(self):
        with open(HELP, encoding="utf-8") as f:
            topics = re.findall(r'\{"([^"]+)",\s*\{\{', f.read())
        cards = {re.sub(r"^\d+\.\s*", "", title.strip()) for title in self.parser.titles}
        self.assertTrue(topics)
        self.assertEqual([topic for topic in topics if topic not in cards], [])


if __name__ == "__main__":
    unittest.main()
