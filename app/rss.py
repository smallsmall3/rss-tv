"""RSS 抓取与条目过滤。

用 feedparser 兼容各种脏 RSS/Atom。从条目里解析出：
  * guid（去重用）
  * 标题、链接（enclosure 直链 / magnet / 正文 magnet）
  * 分类（剧集 / 电影 / 未知，用于过滤出电视和动画）

过滤规则（订阅里配置）：
  * include_filter：正则包含才收
  * exclude_filter：正则排除
  * quality：画质关键字白名单（1080p / 2160p ...）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import feedparser

from .log import log


@dataclass
class FeedItem:
    guid: str = ""
    title: str = ""
    link: str = ""
    published: str = ""
    category: str = "series"  # series / movie / unknown
    magnet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "guid": self.guid,
            "title": self.title,
            "link": self.link,
            "published": self.published,
            "category": self.category,
            "magnet": self.magnet,
        }


_MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]+")

# 剧集类关键词（命中则归为 series）
_SERIES_HINTS = {
    "s01", "s02", "s03", "s04", "s05", "season", "episode",
    "e01", "e02", "e03", "动漫", "动画", "tv series", "anime",
}

# 电影类关键词（命中则归为 movie，不推送）
_MOVIE_HINTS = {
    "bluray", "blu-ray", "remux", "bdremux",
}


def classify_item(title: str) -> str:
    """粗分类：series / movie / unknown。只用于决定是否推送。"""
    low = title.lower()
    # 明确剧集标记
    if re.search(r"(?i)\bS\d{1,2}E\d{1,4}\b", title):
        return "series"
    if re.search(r"第\s*\d+\s*[集话話]", title):
        return "series"
    if any(h in low for h in _SERIES_HINTS):
        return "series"
    # 明确电影标记
    if any(h in low for h in _MOVIE_HINTS):
        return "movie"
    return "unknown"


def parse_feed(content: bytes | str) -> list[FeedItem]:
    """解析 RSS/Atom 内容，返回条目列表。"""
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    feed = feedparser.parse(content)
    items: list[FeedItem] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        if not title:
            continue
        guid = entry.get("id") or entry.get("guid") or entry.get("link") or title
        link = ""
        magnet = ""
        for enc in entry.get("enclosures", []) or []:
            if enc.get("href"):
                link = enc["href"]
                break
        summary = entry.get("summary", "") or entry.get("description", "")
        m = _MAGNET_RE.search(summary)
        if m:
            magnet = m.group(0)
        if not link and not magnet:
            lm = re.search(r"https?://[^\s\"'<>]+\.torrent", summary)
            if lm:
                link = lm.group(0)
        items.append(FeedItem(
            guid=str(guid),
            title=title,
            link=link,
            published=str(entry.get("published", "")),
            category=classify_item(title),
            magnet=magnet,
        ))
    return items


def passes_filters(item: FeedItem, sub: dict[str, Any]) -> bool:
    """判断条目是否通过订阅的过滤规则。"""
    title = item.title
    low = title.lower()

    exclude = sub.get("exclude_filter") or ""
    if exclude:
        try:
            if re.search(exclude, title, re.IGNORECASE):
                return False
        except re.error:
            log.warning("订阅 %s 的 exclude_filter 正则非法：%s", sub.get("id"), exclude)

    include = sub.get("include_filter") or ""
    if include:
        try:
            if not re.search(include, title, re.IGNORECASE):
                return False
        except re.error:
            log.warning("订阅 %s 的 include_filter 正则非法：%s", sub.get("id"), include)

    quality = sub.get("quality") or []
    if quality:
        if not any(q.lower() in low for q in quality):
            return False

    return True
