"""主入口：装配所有组件，启动主循环 + Web 服务器。"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from .config import Config, load_config
from .db import DB
from .emby import EmbyClient
from .hub import Hub
from .log import log, setup_logging
from .notify import Notifier, TelegramChannel
from .tmdb import TmdbClient
from .webui import start_server


def build_hub(config: Config, data_dir: Path) -> Hub:
    db = DB(data_dir / "state.db")
    tmdb = TmdbClient(config.tmdb)
    emby = EmbyClient(config.emby)
    notifier = Notifier([TelegramChannel(config.tg)])
    hub = Hub(
        config=config,
        db=db,
        tmdb=tmdb,
        emby=emby,
        notifier=notifier,
        templates_path=Path("config/notify_templates.txt"),
    )
    hub.reload_templates()
    return hub


def main() -> None:
    config = load_config()
    setup_logging(config.app.log_level)
    data_dir = Path(config.app.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    hub = build_hub(config, data_dir)

    # Web 服务器（独立线程）
    server = start_server(config, hub, config.app.web_host, config.app.web_port)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    log.info("Web 仪表盘：http://%s:%s", config.app.web_host, config.app.web_port)

    # 主循环
    try:
        asyncio.run(hub.run())
    except KeyboardInterrupt:
        log.info("收到退出信号，关闭")
    finally:
        server.shutdown()
        hub.db.close()


if __name__ == "__main__":
    main()
