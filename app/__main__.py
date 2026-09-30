"""rss-tv 服务入口：`python -m app` 启动常驻服务（Docker 用它）。

CLI 工具请用 `python -m app.cli`。
"""

from .main import main

if __name__ == "__main__":
    main()
