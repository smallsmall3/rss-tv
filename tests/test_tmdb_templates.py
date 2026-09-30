"""TMDB 匹配 + Jinja2 模板测试。"""

from __future__ import annotations

import unittest

from app.templates import parse_template_content, render_dict_template
from app.tmdb import TmdbClient, _normalize


class TmdbPickTest(unittest.TestCase):
    def _client(self):
        c = TmdbClient.__new__(TmdbClient)
        c.settings = None
        return c

    def test_pick_best_exact_name(self):
        c = self._client()
        results = [
            {"name": "无职转生", "original_name": "Mushoku Tensei: Isekai Ittara Honki Dasu", "id": 1, "first_air_date": "2021-01-11", "popularity": 100},
            {"name": "异世界叔叔", "original_name": "Isekai Ojisan", "id": 2, "first_air_date": "2022-07-06", "popularity": 40},
        ]
        best = c.pick_best(results, "Mushoku Tensei Isekai Ittara Honki Dasu", 2021)
        self.assertEqual(best["id"], 1)

    def test_normalize(self):
        self.assertEqual(_normalize("S.W.A.T."), "swat")
        self.assertEqual(_normalize("3.10.to.Yuma"), "310toyuma")


class TemplateTest(unittest.TestCase):
    def test_render_dict_template(self):
        tpl = '{"text": "📺 {{ title }} 更新：已入库 {{ done }}/{{ total }} 集（{{ pct }}%）", "image": "{{ poster }}"}'
        ctx = {"title": "无职转生Ⅲ", "done": 3, "total": 49, "pct": 6, "poster": "https://x.jpg"}
        out = render_dict_template(tpl, ctx)
        self.assertEqual(out["text"], "📺 无职转生Ⅲ 更新：已入库 3/49 集（6%）")
        self.assertEqual(out["image"], "https://x.jpg")

    def test_parse_invalid(self):
        with self.assertRaises(ValueError):
            parse_template_content("not a dict")

    def test_conditional_template(self):
        """Jinja2 条件语法（{% if %}）要能正常工作。"""
        tpl = '{"text": "📺 {{ title }}{% if season %} S{{ season }}{% endif %} 更新"}'
        out = render_dict_template(tpl, {"title": "无职转生", "season": 3})
        self.assertEqual(out["text"], "📺 无职转生 S3 更新")


if __name__ == "__main__":
    unittest.main()
