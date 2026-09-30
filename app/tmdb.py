"""TMDB 客户端：搜索剧集、拿中文名/海报/各季集数（分母）。

用 httpx 异步请求，支持反向代理（api_base）和正向代理（proxy），
带内存缓存 + 指数退避重试（tenacity）。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import TmdbSettings
from .log import log


class TmdbError(Exception):
    pass


class TmdbNotFound(TmdbError):
    pass


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _year_of(date: str | None) -> int | None:
    if not date:
        return None
    m = re.match(r"(\d{4})", date)
    return int(m.group(1)) if m else None


@dataclass
class SeriesInfo:
    tmdb_id: int = 0
    name: str = ""
    original_name: str = ""
    year: int | None = None
    poster_path: str = ""
    overview: str = ""
    status: str = ""
    seasons: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_episodes(self) -> int:
        """全季总集数（默认不算 Season 0 特别篇）。"""
        return sum(
            int(s.get("episode_count") or 0)
            for s in self.seasons
            if s.get("season_number") != 0
        )

    def season_episodes(self, season: int) -> int:
        for s in self.seasons:
            if s.get("season_number") == season:
                return int(s.get("episode_count") or 0)
        return 0

    def aired_episodes(self) -> int:
        """已播出的集数（按 air_date 判断）。"""
        total = 0
        for s in self.seasons:
            if s.get("season_number") == 0:
                continue
            for ep in s.get("episodes", []) or []:
                if ep.get("air_date"):
                    total += 1
        return total


class TmdbClient:
    def __init__(self, settings: TmdbSettings):
        self.settings = settings
        self._cache: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {"timeout": 15.0}
        if self.settings.proxy:
            kwargs["proxy"] = self.settings.proxy
        return httpx.AsyncClient(**kwargs)

    def _base(self) -> str:
        return (self.settings.api_base or "https://api.themoviedb.org/3").rstrip("/")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=1, max=10), reraise=True)
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        p = dict(params or {})
        p["api_key"] = self.settings.api_key
        p["language"] = self.settings.language
        async with self._client() as c:
            r = await c.get(f"{self._base()}{path}", params=p)
            r.raise_for_status()
            return r.json()

    async def search_tv(self, name: str, year: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"query": name, "include_adult": "false"}
        if year:
            params["first_air_date_year"] = year
        data = await self._get("/search/tv", params)
        results = data.get("results") or []
        if not results and year:
            params.pop("first_air_date_year", None)
            data = await self._get("/search/tv", params)
            results = data.get("results") or []
        return results

    def pick_best(self, results: list[dict[str, Any]], name: str, year: int | None = None) -> dict[str, Any] | None:
        if not results:
            return None
        target = _normalize(name)

        def score(item: dict[str, Any]) -> tuple[int, int, float]:
            names = {_normalize(item.get("name") or ""), _normalize(item.get("original_name") or "")}
            exact = 1 if target and target in names else 0
            partial = 1 if target and any(target in n or n in target for n in names if n) else 0
            year_hit = 1 if year and _year_of(item.get("first_air_date")) == year else 0
            return (exact, year_hit * 2 + partial, float(item.get("popularity") or 0))

        return max(results, key=score)

    async def resolve(self, name: str | None, tmdb_id: int | None = None, year: int | None = None) -> dict[str, Any]:
        if tmdb_id:
            return await self._get(f"/tv/{int(tmdb_id)}")
        if not name:
            raise TmdbError("既没有 tmdb_id 也没有剧名，无法匹配 TMDB")
        results = await self.search_tv(name, year)
        best = self.pick_best(results, name, year)
        if not best:
            raise TmdbNotFound(f"TMDB 搜不到剧名「{name}」")
        matched = best.get("name") or best.get("original_name") or ""
        if _normalize(name) not in {_normalize(matched), _normalize(best.get("original_name") or "")}:
            log.info("TMDB 名称模糊匹配：%s → %s", name, matched)
        return await self._get(f"/tv/{best['id']}")

    async def series(self, name: str | None, tmdb_id: int | None = None, year: int | None = None) -> SeriesInfo:
        cache_key = f"{tmdb_id}:{name}:{year}"
        async with self._lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        raw = await self.resolve(name, tmdb_id, year)
        info = SeriesInfo(
            tmdb_id=int(raw.get("id") or 0),
            name=raw.get("name") or "",
            original_name=raw.get("original_name") or "",
            year=_year_of(raw.get("first_air_date")),
            poster_path=raw.get("poster_path") or "",
            overview=raw.get("overview") or "",
            status=raw.get("status") or "",
            seasons=raw.get("seasons") or [],
        )
        async with self._lock:
            self._cache[cache_key] = info
        return info

    async def search_by_title(self, raw_title: str) -> dict[str, Any] | None:
        """按发布标题匹配 TMDB（用于 feed 模式配海报/中文名）。

        依次尝试解析出的搜索词，返回 {name, poster, tmdb_id}。
        """
        from .titleparse import search_terms

        for term in search_terms(raw_title):
            try:
                raw = await self.resolve(term)
                return {
                    "name": raw.get("name") or raw.get("original_name") or "",
                    "poster_path": raw.get("poster_path") or "",
                    "tmdb_id": int(raw.get("id") or 0),
                }
            except TmdbNotFound:
                continue
            except TmdbError:
                continue
        return None
