"""Recorded terminal text must remain data in the standalone viewer."""
from html.parser import HTMLParser
import json
from pathlib import Path
import tempfile
import unittest

from living_replay.export_viewer import export_html
from living_replay.store import TimelineStore


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.scripts = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "script":
            self.in_script = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.scripts[-1] += data


class ExportSafetyTests(unittest.TestCase):
    def test_mixed_case_and_whitespace_script_endings_stay_data(self):
        for ending in ("</ScRiPt>", "</script >", "</script\n>"):
            with self.subTest(ending=ending), tempfile.TemporaryDirectory() as tmp:
                attack = ending + '<script>alert("synthetic")</script><img src=x onerror=alert(1)>'
                store = TimelineStore(Path(tmp) / "store")
                try:
                    # Names and terminal output are both embedded into DATA.
                    store.append(attack, "terminal_chunk", {
                        "blob": store.put_blob(attack.encode()), "offset": 0,
                        "length": len(attack), "tool_event": None,
                    })
                    page = export_html(store, [attack], Path(tmp) / "viewer.html", rows=5, cols=150)
                    parser = PageParser()
                    parser.feed(page.read_text(encoding="utf-8"))
                    self.assertEqual(parser.tags.count("script"), 1)
                    self.assertNotIn("img", parser.tags)
                    data_text = parser.scripts[0].split("const DATA = ", 1)[1].split(";\nlet branch", 1)[0]
                    data = json.loads(data_text)
                    self.assertEqual(list(data), [attack])
                    self.assertIn('alert("synthetic")', data[attack][0]["screen"])
                finally:
                    store.db.close()


if __name__ == "__main__":
    unittest.main()
