"""日志初始化。"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("rss-tv")
    if logger.handlers:
        return logger
    logger.setLevel(level.upper())
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"
    ))
    logger.addHandler(h)
    logger.propagate = False
    return logger


log = logging.getLogger("rss-tv")
