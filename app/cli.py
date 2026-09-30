"""命令行工具：订阅管理、手动比对、测试推送。"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .config import load_config
from .db import DB
from .emby import EmbyClient
from .hub import Hub
from .log import log, setup_logging
from .notify import Message, Notifier, TelegramChannel
from .tmdb import TmdbClient


def _build(config, data_dir: Path) -> Hub:
    db = DB(data_dir / "state.db")
    hub = Hub(
        config=config,
        db=db,
        tmdb=TmdbClient(config.tmdb),
        emby=EmbyClient(config.emby),
        notifier=Notifier([TelegramChannel(config.tg)]),
        templates_path=Path("config/notify_templates.txt"),
    )
    hub.reload_templates()
    return hub


def cmd_list(config, args) -> None:
    data_dir = Path(config.app.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    hub = _build(config, data_dir)
    subs = hub.db.list_subscriptions()
    progress = {p["sub_id"]: p for p in hub.db.list_progress()}
    print(f"订阅数：{len(subs)}")
    for s in subs:
        p = progress.get(s["id"], {})
        name = p.get("name") or s.get("tmdb_name") or s.get("name") or s["id"]
        done, total = p.get("done", 0), p.get("total", 0)
        pct = f"{round(done / total * 100)}%" if total else "-"
        print(f"  {name:30s} {done}/{total} ({pct})  mode={s.get('mode', 'show')}")
    hub.db.close()


def cmd_add(config, args) -> None:
    data_dir = Path(config.app.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    hub = _build(config, data_dir)

    async def _resolve():
        sub = {
            "id": args.id or args.name,
            "name": args.name,
            "tmdb_id": args.tmdb_id,
            "rss": args.rss or "",
            "quality": args.quality or [],
            "exclude_filter": args.exclude or "",
            "mode": "show" if args.tmdb_id else "feed",
            "remove_when_done": True,
        }
        if not sub["tmdb_id"] and args.name:
            try:
                raw = await hub.tmdb.resolve(args.name)
                sub["tmdb_id"] = int(raw.get("id") or 0)
                sub["tmdb_name"] = raw.get("name") or args.name
                sub["mode"] = "show"
            except Exception:
                pass
        hub.db.add_subscription(sub)
        print(f"已添加订阅：{sub['name']} (tmdb_id={sub.get('tmdb_id')})")
        await hub.announce_subscribe(sub)

    asyncio.run(_resolve())
    hub.db.close()


def cmd_check(config, args) -> None:
    data_dir = Path(config.app.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    hub = _build(config, data_dir)

    async def _check():
        subs = hub.db.list_subscriptions()
        for sub in subs:
            if sub.get("mode") == "show" and sub.get("tmdb_id"):
                try:
                    await hub.check_and_push(sub)
                except Exception as e:
                    log.warning("比对失败 %s：%s", sub["id"], e)
        print("入库比对完成")

    asyncio.run(_check())
    hub.db.close()


def cmd_test_notify(config, args) -> None:
    notifier = Notifier([TelegramChannel(config.tg)])

    async def _send():
        ok = await notifier.push(Message(title="测试", text="✅ rss-tv 测试消息"))
        print("推送成功" if ok else "推送失败（检查 TG 配置）")

    asyncio.run(_send())


def main() -> None:
    parser = argparse.ArgumentParser(prog="rss-tv", description="PT RSS 电视/动画追更订阅器")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出订阅与进度")
    p_add = sub.add_parser("add", help="添加订阅")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--id", default=None)
    p_add.add_argument("--tmdb-id", type=int, default=None)
    p_add.add_argument("--rss", default=None)
    p_add.add_argument("--quality", nargs="*", default=None)
    p_add.add_argument("--exclude", default=None)
    sub.add_parser("check", help="立即做一次入库比对")
    sub.add_parser("test-notify", help="发一条测试推送")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return
    config = load_config()
    setup_logging(config.app.log_level)
    {"list": cmd_list, "add": cmd_add, "check": cmd_check, "test-notify": cmd_test_notify}[args.cmd](config, args)


if __name__ == "__main__":
    main()
