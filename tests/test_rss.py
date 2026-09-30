"""RSS 解析与过滤测试。"""

from __future__ import annotations

import unittest

from app.rss import FeedItem, classify_item, parse_feed, passes_filters


RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>test</title>
<item>
  <title>Mushoku Tensei S03 2026 1080p CR WEB-DL x264 AAC-ADWeb</title>
  <link>https://pt.example/t/1</link>
  <guid>https://pt.example/t/1</guid>
  <enclosure url="https://pt.example/dl/1.torrent" type="application/x-bittorrent"/>
</item>
<item>
  <title>Some.Movie.2026.1080p.BluRay.x264-GROUP</title>
  <link>https://pt.example/t/2</link>
  <guid>https://pt.example/t/2</guid>
  <description>magnet:?xt=urn:btih:abcdef1234567890</description>
</item>
</channel></rss>
"""


class ParseFeedTest(unittest.TestCase):
    def test_parse_items(self):
        items = parse_feed(RSS_XML)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "Mushoku Tensei S03 2026 1080p CR WEB-DL x264 AAC-ADWeb")
        self.assertEqual(items[0].link, "https://pt.example/dl/1.torrent")
        self.assertEqual(items[1].magnet, "magnet:?xt=urn:btih:abcdef1234567890")

    def test_classify(self):
        self.assertEqual(classify_item("Frieren S01E28 1080p"), "series")
        self.assertEqual(classify_item("Some.Movie.2026.1080p.BluRay"), "movie")
        self.assertEqual(classify_item("某部剧.第05集.1080p"), "series")


class FilterTest(unittest.TestCase):
    def _sub(self, **kw):
        return {"id": "t", "name": "t", "exclude_filter": "", "include_filter": "", "quality": [], **kw}

    def test_quality_whitelist(self):
        sub = self._sub(quality=["1080p"])
        self.assertTrue(passes_filters(FeedItem(title="Foo S01E01 1080p WEB-DL"), sub))
        self.assertFalse(passes_filters(FeedItem(title="Foo S01E01 720p WEB-DL"), sub))

    def test_exclude(self):
        sub = self._sub(exclude_filter="预告|花絮")
        self.assertFalse(passes_filters(FeedItem(title="Foo S01E01 预告"), sub))
        self.assertTrue(passes_filters(FeedItem(title="Foo S01E01 1080p"), sub))

    def test_include(self):
        sub = self._sub(include_filter="1080p")
        self.assertTrue(passes_filters(FeedItem(title="Foo 1080p"), sub))
        self.assertFalse(passes_filters(FeedItem(title="Foo 720p"), sub))


if __name__ == "__main__":
    unittest.main()
