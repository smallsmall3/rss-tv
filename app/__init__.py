"""rss-tv：PT RSS 电视/动画追更订阅器。

只推送不接管下载器。RSS → 标题识别 → TMDB → Emby 比对 → Telegram 推送 → Web 仪表盘。
"""

from .version import __version__

__all__ = ["__version__"]
