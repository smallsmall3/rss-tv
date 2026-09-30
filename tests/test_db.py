"""数据库存储测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.db import DB


class DBTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = DB(self.tmp / "state.db")

    def tearDown(self):
        self.db.close()

    def test_add_and_list_subscription(self):
        self.db.add_subscription({
            "id": "show1", "name": "无职转生", "tmdb_id": 111110,
            "rss": "http://x", "quality": ["1080p"], "mode": "show",
        })
        subs = self.db.list_subscriptions()
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["name"], "无职转生")
        self.assertEqual(subs[0]["quality"], ["1080p"])

    def test_remove(self):
        self.db.add_subscription({"id": "s1", "name": "x", "rss": "http://x"})
        self.db.remove_subscription("s1")
        self.assertEqual(len(self.db.list_subscriptions()), 0)

    def test_seen(self):
        self.assertFalse(self.db.is_seen("s1", "g1"))
        self.db.mark_seen("s1", "g1")
        self.assertTrue(self.db.is_seen("s1", "g1"))

    def test_progress(self):
        self.db.save_progress("s1", {"tmdb_id": 1, "name": "x", "done": 3, "total": 24})
        p = self.db.get_progress("s1")
        self.assertEqual(p["done"], 3)
        self.assertEqual(p["total"], 24)


if __name__ == "__main__":
    unittest.main()
