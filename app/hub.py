"""核心编排器：把 RSS 订阅、TMDB、Emby、推送、模板串成一条追更流水线。

主循环：
  1. 轮询每个订阅的 RSS，过滤出电视/动画类新种
  2. 新种 → 解析标题 → TMDB 拿中文名/海报/总集数（分母）
  3. 查 Emby 已入库集数（分子）→ 推送进度
  4. 分子 = 分母 → 推送完成通知 + 退订

只负责「通知 + 记账 + 退订」，不接管下载器。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .config import Config
from .db import DB
from .emby import EmbyClient
from .log import log
from .notify import Message, Notifier
from .rss import FeedItem, parse_feed, passes_filters
from .templates import load_templates, render_dict_template
from .titleparse import ParsedTitle, parse_release_title
from .tmdb import TmdbClient, TmdbError


def _poster_url(path: str, size: str = "w500") -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return f"https://image.tmdb.org/t/p/{size}{path}"


@dataclass
class Hub:
    config: Config
    db: DB
    tmdb: TmdbClient
    emby: EmbyClient
    notifier: Notifier
    templates_path: Path | None = None
    _templates: dict[str, str] = field(default_factory=dict)
    _http: httpx.AsyncClient | None = None
    _poster_cache: dict[str, str] = field(default_factory=dict)
    _running: bool = False

    # ---------------- 模板 ----------------

    def reload_templates(self) -> None:
        self._templates = load_templates(self.templates_path)

    def _notify_enabled(self, event: str) -> bool:
        """判断某类通知是否开启（4 类通知各自独立开关）。"""
        flags = {
            "feed_new": self.config.app.notify_feed_new,
            "show_new": self.config.app.notify_show_new,
            "library_update": self.config.app.notify_library_update,
            "done": self.config.app.notify_done,
        }
        return flags.get(event, True)

    def _render(self, event: str, context: dict[str, Any]) -> dict[str, str] | None:
        tpl = self._templates.get(event)
        if not tpl:
            return None
        try:
            return render_dict_template(tpl, context)
        except Exception as e:
            log.warning("事件 %s 模板解析失败：%s", event, e)
            return None

    # ---------------- 海报 ----------------

    async def _poster_url_for(self, tmdb_id: int) -> str:
        key = f"p:{tmdb_id}"
        if key in self._poster_cache:
            return self._poster_cache[key]
        try:
            raw = await self.tmdb.resolve(None, tmdb_id=tmdb_id)
            url = _poster_url(raw.get("poster_path") or "")
            self._poster_cache[key] = url
            return url
        except Exception:
            return ""

    # ---------------- 订阅管理 ----------------

    def add_subscription(self, sub: dict[str, Any]) -> None:
        self.db.add_subscription(sub)

    def remove_subscription(self, sub_id: str) -> None:
        self.db.remove_subscription(sub_id)

    # ---------------- RSS 抓取 ----------------

    async def _fetch_rss(self, url: str) -> bytes:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=20.0, follow_redirects=True)
        r = await self._http.get(url)
        r.raise_for_status()
        return r.content

    async def poll_subscription(self, sub: dict[str, Any]) -> None:
        sub_id = sub["id"]
        rss_url = sub.get("rss") or ""
        if not rss_url:
            return
        try:
            content = await self._fetch_rss(rss_url)
            items = parse_feed(content)
        except Exception as e:
            log.warning("订阅 %s RSS 抓取失败：%s", sub_id, e)
            return

        new_items = [
            it for it in items
            if passes_filters(it, sub) and it.category != "movie"
        ]
        for item in new_items:
            if self.db.is_seen(sub_id, item.guid):
                continue
            self.db.mark_seen(sub_id, item.guid)
            await self._handle_new_item(sub, item)

    async def _handle_new_item(self, sub: dict[str, Any], item: FeedItem) -> None:
        parsed = parse_release_title(item.title)
        mode = sub.get("mode", "show")
        tmdb_id = sub.get("tmdb_id")

        if mode == "show" and tmdb_id:
            await self._push_progress(sub, item, parsed, tmdb_id)
        else:
            await self._push_feed(sub, item, parsed)

    # ---------------- feed 模式（纯播报） ----------------

    async def _push_feed(self, sub: dict[str, Any], item: FeedItem, parsed: ParsedTitle) -> None:
        if not self._notify_enabled("feed_new"):
            log.debug("新种通知已关闭，跳过推送：%s", item.title)
            return
        context: dict[str, Any] = {
            "title": parsed.title or item.title,
            "raw_title": item.title,
            "year": parsed.year or "",
            "season": parsed.season or "",
            "episode": parsed.episode or "",
            "link": item.link or item.magnet,
            "image": "",
        }
        # 尝试匹配 TMDB 配海报/中文名
        try:
            hit = await self.tmdb.search_by_title(item.title)
            if hit:
                context["image"] = _poster_url(hit["poster_path"])
                if hit["name"]:
                    context["title"] = hit["name"]
        except Exception:
            pass

        rendered = self._render("feed_new", context)
        if rendered:
            msg = Message(
                title=str(context["title"]),
                text=rendered.get("text", ""),
                image=rendered.get("image", context["image"]),
                link=item.link or item.magnet,
                image_caption=rendered.get("image_caption", ""),
            )
        else:
            msg = Message(
                title=str(context["title"]),
                text=f"📡 发现新种：{context['title']}",
                image=context["image"],
                link=item.link or item.magnet,
                image_caption=str(context["title"]),
            )
        await self.notifier.push(msg)

    # ---------------- show 模式（比对进度） ----------------

    async def _push_progress(self, sub: dict[str, Any], item: FeedItem, parsed: ParsedTitle, tmdb_id: int) -> None:
        sub_id = sub["id"]
        try:
            series = await self.tmdb.series(None, tmdb_id=tmdb_id)
        except TmdbError as e:
            log.warning("订阅 %s TMDB 查询失败：%s", sub_id, e)
            return

        season = parsed.season
        if season is not None:
            total = series.season_episodes(season)
            if total == 0:
                total = series.total_episodes
        else:
            total = series.total_episodes

        lib = None
        try:
            lib = await self.emby.find_series(tmdb_id, series.name)
        except Exception as e:
            log.warning("订阅 %s Emby 查询失败：%s", sub_id, e)

        done = 0
        missing = ""
        if lib and lib.found:
            if season is not None:
                done = lib.seasons.get(season, 0)
                if done < total:
                    missing = f"S{season:02d}E{done + 1:02d}-E{total:02d}"
            else:
                done = lib.total_done

        pct = round(done / total * 100) if total else 0
        poster = _poster_url(series.poster_path)

        self.db.save_progress(sub_id, {
            "tmdb_id": tmdb_id,
            "name": series.name,
            "season": season,
            "total": total,
            "aired": total,
            "done": done,
            "missing": missing,
            "poster_path": series.poster_path,
        })

        context = {
            "title": series.name,
            "original_name": series.original_name,
            "year": series.year or "",
            "season": season or 1,
            "episode": parsed.episode or "",
            "total": total,
            "done": done,
            "missing": missing,
            "pct": pct,
            "image": poster,
            "link": item.link or item.magnet,
        }

        if done >= total and total > 0:
            await self._push_done(sub, context)
        else:
            await self._push_update(sub, context)

    async def _push_update(self, sub: dict[str, Any], context: dict[str, Any]) -> None:
        if not self._notify_enabled("show_new"):
            log.debug("更新进度通知已关闭，跳过推送：%s", context.get("title"))
            return
        progress = f"入库 {context['done']}/{context['total']} 集（{context['pct']}%）"
        if context.get("missing"):
            progress += f"｜待入库 {context['missing']}"
        rendered = self._render("show_new", context)
        if rendered:
            msg = Message(
                title=context["title"],
                text=rendered.get("text", ""),
                image=rendered.get("image", ""),
                link=context.get("link", ""),
                image_caption=rendered.get("image_caption", ""),
            )
        else:
            msg = Message(
                title=context["title"],
                text=f"📺 {context['title']} 更新 {progress}",
                image=context["image"],
                link=context.get("link", ""),
                image_caption=f"{context['title']} {progress}",
            )
        await self.notifier.push(msg)

    async def _push_done(self, sub: dict[str, Any], context: dict[str, Any]) -> None:
        if not self._notify_enabled("done"):
            log.debug("完结通知已关闭，跳过推送：%s", context.get("title"))
        else:
            rendered = self._render("done", context)
            if rendered:
                msg = Message(
                    title=context["title"],
                    text=rendered.get("text", ""),
                    image=rendered.get("image", ""),
                    image_caption=rendered.get("image_caption", ""),
                )
            else:
                msg = Message(
                    title=context["title"],
                    text=f"🎉 {context['title']} 已全部入库（{context['total']} 集）",
                    image=context["image"],
                    image_caption=f"🎉 {context['title']} 全部入库",
                )
            await self.notifier.push(msg)

        if sub.get("remove_when_done", True):
            log.info("订阅 %s 已完成，自动退订", sub["id"])
            self.db.remove_subscription(sub["id"])

    # ---------------- 订阅添加通知 ----------------

    async def announce_subscribe(self, sub: dict[str, Any]) -> None:
        tmdb_id = sub.get("tmdb_id")
        name = sub.get("name") or ""
        poster = ""
        if tmdb_id:
            try:
                raw = await self.tmdb.resolve(None, tmdb_id=tmdb_id)
                name = raw.get("name") or name
                poster = _poster_url(raw.get("poster_path") or "")
            except Exception:
                pass
        context = {"title": name, "year": sub.get("year", ""), "image": poster}
        rendered = self._render("sub_added", context)
        if rendered:
            msg = Message(
                title=name, text=rendered.get("text", ""),
                image=rendered.get("image", poster),
                image_caption=rendered.get("image_caption", ""),
            )
        else:
            msg = Message(
                title=name, text=f"✅ {name} 已添加订阅", image=poster,
                image_caption=f"✅ {name} 已添加订阅",
            )
        await self.notifier.push(msg)

    # ---------------- 主循环 ----------------

    async def run(self) -> None:
        self._running = True
        self.reload_templates()
        log.info("rss-tv 启动，轮询间隔 %ss", self.config.app.poll_interval)
        last_emby_check = 0.0
        while self._running:
            try:
                subs = self.db.list_subscriptions()
                for sub in subs:
                    await self.poll_subscription(sub)
                now = time.time()
                if now - last_emby_check >= self.config.app.emby_check_interval:
                    await self._reconcile(subs)
                    last_emby_check = now
            except Exception as e:
                log.exception("主循环异常：%s", e)
            await asyncio.sleep(self.config.app.poll_interval)

    async def _reconcile(self, subs: list[dict[str, Any]]) -> None:
        """全量比对：补推停机期间的入库。"""
        for sub in subs:
            if sub.get("mode") != "show" or not sub.get("tmdb_id"):
                continue
            try:
                await self.check_and_push(sub)
            except Exception as e:
                log.warning("订阅 %s 比对失败：%s", sub["id"], e)

    async def check_and_push(self, sub: dict[str, Any]) -> None:
        """单次入库比对并推送（供 reconcile 和手动 check 用）。

        这是「媒体库新入库」场景（library_update），有自己独立的通知开关；
        完结时仍走 done 开关。
        """
        tmdb_id = sub["tmdb_id"]
        series = await self.tmdb.series(None, tmdb_id=tmdb_id)
        lib = await self.emby.find_series(tmdb_id, series.name)
        total = series.total_episodes
        done = lib.total_done if lib and lib.found else 0
        prev = self.db.get_progress(sub["id"])
        prev_done = (prev or {}).get("done", 0)
        if done > prev_done:
            poster = _poster_url(series.poster_path)
            context = {
                "title": series.name, "total": total, "done": done,
                "pct": round(done / total * 100) if total else 0,
                "missing": "", "image": poster, "season": 1, "episode": "",
                "link": "", "original_name": series.original_name,
                "year": series.year or "",
            }
            if done >= total and total > 0:
                await self._push_done(sub, context)
            else:
                # library_update 有独立开关
                if not self._notify_enabled("library_update"):
                    log.debug("媒体库新入库通知已关闭，跳过推送：%s", series.name)
                else:
                    await self._push_update(sub, context)
            self.db.save_progress(sub["id"], {
                "tmdb_id": tmdb_id, "name": series.name, "season": None,
                "total": total, "aired": total, "done": done,
                "missing": "", "poster_path": series.poster_path,
            })

    # ---------------- 对外查询 ----------------

    async def dashboard_data(self) -> dict[str, Any]:
        """Web 仪表盘数据：订阅 + 进度 + 状态。"""
        subs = self.db.list_subscriptions()
        progress = {p["sub_id"]: p for p in self.db.list_progress()}
        cards = []
        for sub in subs:
            p = progress.get(sub["id"])
            poster = _poster_url(p["poster_path"]) if p and p.get("poster_path") else ""
            total = (p or {}).get("total", 0)
            done = (p or {}).get("done", 0)
            cards.append({
                "id": sub["id"],
                "name": (p or {}).get("name") or sub.get("tmdb_name") or sub.get("name", ""),
                "tmdb_id": sub.get("tmdb_id"),
                "mode": sub.get("mode", "show"),
                "done": done,
                "total": total,
                "pct": round(done / total * 100) if total else 0,
                "poster": poster,
                "rss": sub.get("rss", ""),
                "created_at": sub.get("created_at", 0),
            })
        return {
            "subscriptions": cards,
            "total": len(subs),
            "catching": len([c for c in cards if c["total"] == 0 or c["done"] < c["total"]]),
            "done": len([c for c in cards if c["total"] > 0 and c["done"] >= c["total"]]),
        }
