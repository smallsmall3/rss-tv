"""Hub 通知开关测试。"""

from __future__ import annotations

import unittest

from app.config import Config
from app.hub import Hub


class NotifySwitchTest(unittest.TestCase):
    def _hub(self) -> Hub:
        config = Config()
        hub = Hub.__new__(Hub)
        hub.config = config
        return hub

    def test_default_all_enabled(self):
        hub = self._hub()
        self.assertTrue(hub._notify_enabled("feed_new"))
        self.assertTrue(hub._notify_enabled("show_new"))
        self.assertTrue(hub._notify_enabled("library_update"))
        self.assertTrue(hub._notify_enabled("done"))

    def test_disable_single(self):
        hub = self._hub()
        hub.config.app.notify_feed_new = False
        self.assertFalse(hub._notify_enabled("feed_new"))
        self.assertTrue(hub._notify_enabled("show_new"))
        self.assertTrue(hub._notify_enabled("library_update"))
        self.assertTrue(hub._notify_enabled("done"))

    def test_unknown_event_default_true(self):
        hub = self._hub()
        # 未知事件（如 sub_added）不受这 4 个开关控制，默认开
        self.assertTrue(hub._notify_enabled("sub_added"))


if __name__ == "__main__":
    unittest.main()
