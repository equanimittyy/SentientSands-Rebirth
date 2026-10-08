import os
import unittest
from html.parser import HTMLParser

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dashboard", "web", "index.html")


class TutorialLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = set()
        self.links = []
        self.inside = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section":
            self.sections.add(attrs.get("id"))
            self.inside = attrs.get("id") == "tutorial"
        elif self.inside and tag == "a" and attrs.get("href", "").startswith("#"):
            self.links.append(attrs["href"][1:])

    def handle_endtag(self, tag):
        if tag == "section":
            self.inside = False


class TutorialTest(unittest.TestCase):
    def test_tab_links_name_a_page(self):
        parser = TutorialLinks()
        with open(INDEX, encoding="utf-8") as f:
            parser.feed(f.read())
        self.assertTrue(parser.links)
        self.assertEqual([link for link in parser.links if link not in parser.sections], [])


if __name__ == "__main__":
    unittest.main()
