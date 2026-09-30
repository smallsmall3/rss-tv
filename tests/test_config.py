"""配置加载测试。"""

from __future__ import annotations

import os
import unittest

from app.config import Config, load_config


class ConfigTest(unittest.TestCase):
    def test_defaults(self):
        c = Config()
        self.assertFalse(c.tg.enabled)
        self.assertFalse(c.tmdb.enabled)
        self.assertFalse(c.emby.enabled)
        self.assertEqual(c.app.web_port, 18080)

    def test_env_overrides(self):
        old = os.environ.get("RMH_WEB_PORT")
        os.environ["RMH_WEB_PORT"] = "19090"
        os.environ["RMH_TG_BOT_TOKEN"] = "abc:def"
        os.environ["RMH_TG_CHAT_ID"] = "12345"
        try:
            c = Config()
            c._apply_env()
            self.assertEqual(c.app.web_port, 19090)
            self.assertTrue(c.tg.enabled)
        finally:
            if old is None:
                os.environ.pop("RMH_WEB_PORT", None)
            else:
                os.environ["RMH_WEB_PORT"] = old
            os.environ.pop("RMH_TG_BOT_TOKEN", None)
            os.environ.pop("RMH_TG_CHAT_ID", None)

    def test_redact(self):
        c = Config()
        c.tmdb.api_key = "secret123"
        d = c.as_dict(redact=True)
        self.assertEqual(d["tmdb"]["api_key"], "******")


if __name__ == "__main__":
    unittest.main()
