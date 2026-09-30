"""标题解析测试：从 PT 发布标题还原片名/年份/季集。

覆盖：片名自带点号、片名含年份、日番片源标签、中文标题、绝对集数、合集标记。
"""

from __future__ import annotations

import unittest

from app.titleparse import parse_release_title, search_terms


class MovieTest(unittest.TestCase):
    def test_movie_with_year(self):
        p = parse_release_title("超新星.2020.1080p.BluRay.x264-GROUP")
        self.assertEqual(p.title, "超新星")
        self.assertEqual(p.year, 2020)
        self.assertTrue(p.confident)

    def test_english_movie(self):
        p = parse_release_title("The.Matrix.1999.2160p.UHD.BluRay.REMUX.HDR.HEVC.TrueHD.7.1.Atmos")
        self.assertEqual(p.title, "The Matrix")
        self.assertEqual(p.year, 1999)

    def test_dotted_abbreviation(self):
        p = parse_release_title("S.W.A.T.2017.1080p.BluRay.x264-GROUP")
        self.assertEqual(p.title, "S.W.A.T")
        self.assertEqual(p.year, 2017)

    def test_dotted_number_title(self):
        p = parse_release_title("3.10.to.Yuma.2007.1080p.BluRay.x264-GROUP")
        self.assertEqual(p.title, "3.10.to.Yuma")
        self.assertEqual(p.year, 2007)


class EpisodeTest(unittest.TestCase):
    def test_se_ep(self):
        p = parse_release_title("Some.Show.S01E05.1080p.WEB-DL.AAC-GROUP")
        self.assertEqual(p.title, "Some Show")
        self.assertEqual(p.season, 1)
        self.assertEqual(p.episode, 5)

    def test_chinese_episode(self):
        p = parse_release_title("某部剧.第05集.1080p.WEB-DL-GROUP")
        self.assertEqual(p.title, "某部剧")
        self.assertEqual(p.episode, 5)

    def test_bare_season(self):
        p = parse_release_title("The Girl in Blue S01 1080p TX（2026）全24集")
        self.assertEqual(p.title, "The Girl in Blue")
        self.assertEqual(p.season, 1)
        self.assertEqual(p.year, 2026)
        self.assertTrue(p.complete)


class AnimeSourceTagTest(unittest.TestCase):
    """日番片源平台标签（CR / B-Global / Baha / AT-X）不该留在片名里。"""

    def test_mushoku_tensei_s03(self):
        raw = "Mushoku Tensei Isekai Ittara Honki Dasu S03 2026 1080p CR WEB-DL x264 AAC-ADWeb"
        p = parse_release_title(raw)
        self.assertEqual(p.title, "Mushoku Tensei Isekai Ittara Honki Dasu")
        self.assertEqual(p.season, 3)
        self.assertEqual(p.year, 2026)
        self.assertTrue(p.confident)
        self.assertEqual(search_terms(raw), ["Mushoku Tensei Isekai Ittara Honki Dasu"])

    def test_b_global(self):
        p = parse_release_title("Frieren S01E28 1080p B-Global WEB-DL AAC H.264-Thome")
        self.assertEqual(p.title, "Frieren")
        self.assertEqual(p.season, 1)
        self.assertEqual(p.episode, 28)

    def test_baha(self):
        p = parse_release_title("Oshi no Ko S02 2024 1080p Baha WEB-DL H.264-ADWeb")
        self.assertEqual(p.title, "Oshi no Ko")
        self.assertEqual(p.season, 2)

    def test_atx(self):
        p = parse_release_title("Sakuna S01 1080p AT-X WEB-DL H.265-GROUP")
        self.assertEqual(p.title, "Sakuna")
        self.assertEqual(p.season, 1)


class AliasTest(unittest.TestCase):
    def test_chinese_alias_from_bracket(self):
        """国产动漫：拼音标题，方括号里带中文名。"""
        raw = "[动漫]Su Dong Po Yu Hang Zhou De Gu Shi 2026 S01E32 2160p WEB-DL"
        terms = search_terms(raw)
        self.assertIn("Su Dong Po Yu Hang Zhou De Gu Shi", terms)


if __name__ == "__main__":
    unittest.main()
