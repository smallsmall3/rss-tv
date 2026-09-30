"""SQLite 状态存储：订阅、已见条目、入库进度快照。

零额外依赖（标准库 sqlite3），线程安全（锁保护）。三类状态：
  * subscriptions：订阅清单（id / 名称 / tmdb_id / rss / 过滤规则）
  * seen_items：已推送过的 RSS 条目（去重 + 停机恢复）
  * progress：每部剧的入库进度快照（分子/分母），供 Web UI 展示
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    tmdb_id INTEGER,
                    tmdb_name TEXT,
                    rss TEXT,
                    quality TEXT,
                    exclude_filter TEXT,
                    include_filter TEXT,
                    remove_when_done INTEGER DEFAULT 1,
                    mode TEXT DEFAULT 'show',
                    created_at REAL
                );
                CREATE TABLE IF NOT EXISTS seen_items (
                    sub_id TEXT,
                    guid TEXT,
                    seen_at REAL,
                    PRIMARY KEY (sub_id, guid)
                );
                CREATE TABLE IF NOT EXISTS progress (
                    sub_id TEXT PRIMARY KEY,
                    tmdb_id INTEGER,
                    name TEXT,
                    season INTEGER,
                    total INTEGER,
                    aired INTEGER,
                    done INTEGER,
                    missing TEXT,
                    poster_path TEXT,
                    updated_at REAL
                );
                """
            )
            self._conn.commit()

    # ---------------- 订阅 ----------------

    def add_subscription(self, sub: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO subscriptions
                   (id, name, tmdb_id, tmdb_name, rss, quality, exclude_filter,
                    include_filter, remove_when_done, mode, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    sub["id"], sub.get("name", ""), sub.get("tmdb_id"),
                    sub.get("tmdb_name", ""), sub.get("rss", ""),
                    json.dumps(sub.get("quality", [])),
                    sub.get("exclude_filter", ""), sub.get("include_filter", ""),
                    int(bool(sub.get("remove_when_done", True))),
                    sub.get("mode", "show"), sub.get("created_at", time.time()),
                ),
            )
            self._conn.commit()

    def remove_subscription(self, sub_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM subscriptions WHERE id=?", (sub_id,))
            self._conn.commit()

    def list_subscriptions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM subscriptions ORDER BY created_at"
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["quality"] = json.loads(d.get("quality") or "[]")
            out.append(d)
        return out

    def get_subscription(self, sub_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM subscriptions WHERE id=?", (sub_id,)
            ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["quality"] = json.loads(d.get("quality") or "[]")
        return d

    # ---------------- 已见条目 ----------------

    def is_seen(self, sub_id: str, guid: str) -> bool:
        with self._lock:
            r = self._conn.execute(
                "SELECT 1 FROM seen_items WHERE sub_id=? AND guid=?",
                (sub_id, guid),
            ).fetchone()
        return r is not None

    def mark_seen(self, sub_id: str, guid: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO seen_items (sub_id, guid, seen_at) VALUES (?,?,?)",
                (sub_id, guid, time.time()),
            )
            self._conn.commit()

    # ---------------- 进度快照 ----------------

    def save_progress(self, sub_id: str, p: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO progress
                   (sub_id, tmdb_id, name, season, total, aired, done, missing,
                    poster_path, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    sub_id, p.get("tmdb_id"), p.get("name"), p.get("season"),
                    p.get("total"), p.get("aired"), p.get("done"),
                    p.get("missing"), p.get("poster_path"), time.time(),
                ),
            )
            self._conn.commit()

    def list_progress(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM progress ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_progress(self, sub_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self._conn.execute(
                "SELECT * FROM progress WHERE sub_id=?", (sub_id,)
            ).fetchone()
        return dict(r) if r else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()
