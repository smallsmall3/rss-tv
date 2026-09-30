"""Emby / Jellyfin 客户端：取真实已入库集数（分子）。

通过 /Items 接口查某部剧（按 tmdb_id 的 ProviderIds 或名称）的各季集数。
用 httpx 异步请求，带缓存 + 重试。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import EmbySettings
from .log import log


class EmbyError(Exception):
    pass


@dataclass
class LibraryStatus:
    """某部剧在媒体库里的入库状态。"""

    tmdb_id: int = 0
    name: str = ""
    found: bool = False
    seasons: dict[int, int] = field(default_factory=dict)  # season_number -> 已入库集数

    @property
    def total_done(self) -> int:
        return sum(self.seasons.values())


class EmbyClient:
    def __init__(self, settings: EmbySettings):
        self.settings = settings
        self._cache: dict[str, LibraryStatus] = {}
        self._lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {"timeout": 15.0}
        if not self.settings.verify_tls:
            kwargs["verify"] = False
        return httpx.AsyncClient(**kwargs)

    def _base(self) -> str:
        return self.settings.url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"X-Emby-Token": self.settings.api_key}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1.5, min=1, max=10), reraise=True)
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with self._client() as c:
            r = await c.get(f"{self._base()}{path}", params=params, headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def find_series(self, tmdb_id: int, name: str | None = None) -> LibraryStatus | None:
        """按 tmdb_id（ProviderIds）找剧，找不到回退名称搜索。"""
        cache_key = f"{tmdb_id}:{name}"
        async with self._lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        result: LibraryStatus | None = None
        if tmdb_id:
            try:
                params = {
                    "Recursive": "true",
                    "IncludeItemTypes": "Series",
                    "Fields": "ProviderIds",
                }
                data = await self._get("/Items", params)
                for it in data.get("Items") or []:
                    pids = it.get("ProviderIds") or {}
                    if str(pids.get("Tmdb")) == str(tmdb_id):
                        result = await self._series_status(it["Id"], tmdb_id, it.get("Name") or name or "")
                        break
            except Exception as e:
                log.warning("Emby ProviderIds 查询失败，回退名称搜索：%s", e)

        if result is None and name:
            try:
                params = {
                    "Recursive": "true",
                    "IncludeItemTypes": "Series",
                    "SearchTerm": name,
                }
                data = await self._get("/Items", params)
                items = data.get("Items") or []
                if items:
                    it = items[0]
                    result = await self._series_status(it["Id"], tmdb_id, it.get("Name") or name)
            except Exception as e:
                log.warning("Emby 名称搜索失败：%s", e)

        if result is None:
            result = LibraryStatus(tmdb_id=tmdb_id, name=name or "", found=False)

        async with self._lock:
            self._cache[cache_key] = result
        return result

    async def _series_status(self, series_id: str, tmdb_id: int, name: str) -> LibraryStatus:
        """拉一部剧的全部集，统计各季入库数。"""
        params = {
            "ParentId": series_id,
            "Recursive": "true",
            "IncludeItemTypes": "Episode",
            "Fields": "ParentIndexNumber",
        }
        data = await self._get("/Items", params)
        seasons: dict[int, int] = {}
        for ep in data.get("Items") or []:
            sn = ep.get("ParentIndexNumber")
            if sn is not None:
                seasons[int(sn)] = seasons.get(int(sn), 0) + 1
        return LibraryStatus(tmdb_id=tmdb_id, name=name, found=True, seasons=seasons)
