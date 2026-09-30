"""配置系统：环境变量（.env）+ config.yaml 两层，密钥优先环境变量。

配置分四组：telegram / tmdb / emby / app，每组的字段都登记在
UI_EDITABLE（Web 可编辑），敏感字段登记在 SECRET_FIELDS（前端脱敏）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


@dataclass
class TelegramSettings:
    bot_token: str = ""
    chat_id: str = ""
    thread_id: str = ""
    api_base: str = ""          # 反向代理（替换 api.telegram.org）
    proxy: str = ""             # 正向代理 http://host:port

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass
class TmdbSettings:
    api_key: str = ""
    api_base: str = ""
    proxy: str = ""
    language: str = "zh-CN"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)


@dataclass
class EmbySettings:
    url: str = ""
    api_key: str = ""
    user_id: str = ""
    count_aired_only: bool = True
    include_specials: bool = False
    verify_tls: bool = False

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.api_key)


@dataclass
class AppSettings:
    data_dir: str = "data"
    poll_interval: int = 300          # RSS 轮询间隔（秒）
    emby_check_interval: int = 3600   # 媒体库比对间隔（秒）
    auto_subscribe: bool = False
    log_level: str = "INFO"
    web_host: str = "0.0.0.0"
    web_port: int = 18080
    web_token: str = ""               # Web UI 访问令牌（空=不鉴权）
    # 4 类通知的独立开关（默认全开，可单独关闭某一类）
    notify_feed_new: bool = True      # 发现新种
    notify_show_new: bool = True      # 剧集更新进度
    notify_library_update: bool = True  # 媒体库新入库
    notify_done: bool = True          # 追完/完结


@dataclass
class Config:
    tg: TelegramSettings = field(default_factory=TelegramSettings)
    tmdb: TmdbSettings = field(default_factory=TmdbSettings)
    emby: EmbySettings = field(default_factory=EmbySettings)
    app: AppSettings = field(default_factory=AppSettings)

    # 环境变量 → (配置对象, 字段名, 类型)
    _ENV_MAP: ClassVar[dict[str, tuple[str, str, str]]] = {
        "RMH_TG_BOT_TOKEN": ("tg", "bot_token", "str"),
        "RMH_TG_CHAT_ID": ("tg", "chat_id", "str"),
        "RMH_TG_THREAD_ID": ("tg", "thread_id", "str"),
        "RMH_TG_API_BASE": ("tg", "api_base", "str"),
        "RMH_TG_PROXY": ("tg", "proxy", "str"),
        "RMH_TMDB_API_KEY": ("tmdb", "api_key", "str"),
        "RMH_TMDB_API_BASE": ("tmdb", "api_base", "str"),
        "RMH_TMDB_PROXY": ("tmdb", "proxy", "str"),
        "RMH_TMDB_LANGUAGE": ("tmdb", "language", "str"),
        "RMH_EMBY_URL": ("emby", "url", "str"),
        "RMH_EMBY_API_KEY": ("emby", "api_key", "str"),
        "RMH_EMBY_USER_ID": ("emby", "user_id", "str"),
        "RMH_EMBY_COUNT_AIRED_ONLY": ("emby", "count_aired_only", "bool"),
        "RMH_EMBY_INCLUDE_SPECIALS": ("emby", "include_specials", "bool"),
        "RMH_EMBY_VERIFY_TLS": ("emby", "verify_tls", "bool"),
        "RMH_POLL_INTERVAL": ("app", "poll_interval", "int"),
        "RMH_EMBY_CHECK_INTERVAL": ("app", "emby_check_interval", "int"),
        "RMH_AUTO_SUBSCRIBE": ("app", "auto_subscribe", "bool"),
        "RMH_LOG_LEVEL": ("app", "log_level", "str"),
        "RMH_WEB_HOST": ("app", "web_host", "str"),
        "RMH_WEB_PORT": ("app", "web_port", "int"),
        "RMH_WEB_TOKEN": ("app", "web_token", "str"),
        "RMH_DATA_DIR": ("app", "data_dir", "str"),
        "RMH_NOTIFY_FEED_NEW": ("app", "notify_feed_new", "bool"),
        "RMH_NOTIFY_SHOW_NEW": ("app", "notify_show_new", "bool"),
        "RMH_NOTIFY_LIBRARY_UPDATE": ("app", "notify_library_update", "bool"),
        "RMH_NOTIFY_DONE": ("app", "notify_done", "bool"),
    }

    UI_EDITABLE: ClassVar[dict[str, list[str]]] = {
        "telegram": ["bot_token", "chat_id", "thread_id", "api_base", "proxy"],
        "tmdb": ["api_key", "api_base", "proxy", "language"],
        "emby": ["url", "api_key", "user_id", "count_aired_only", "include_specials", "verify_tls"],
        "app": ["poll_interval", "emby_check_interval", "auto_subscribe", "web_token",
                "notify_feed_new", "notify_show_new", "notify_library_update", "notify_done"],
    }

    SECRET_FIELDS: ClassVar[set[str]] = {
        "bot_token", "api_key", "proxy", "web_token",
    }

    def _apply_env(self) -> None:
        for env_key, (obj_name, field_name, typ) in self._ENV_MAP.items():
            val = os.environ.get(env_key)
            if val is None or val == "":
                continue
            obj = getattr(self, obj_name)
            if typ == "int":
                try:
                    setattr(obj, field_name, int(val))
                except ValueError:
                    pass
            elif typ == "bool":
                setattr(obj, field_name, val.lower() in ("1", "true", "yes", "on"))
            else:
                setattr(obj, field_name, val)

    def _apply_yaml(self, data: dict[str, Any]) -> None:
        for section in ("telegram", "tmdb", "emby", "app"):
            raw = data.get(section) or {}
            if not isinstance(raw, dict):
                continue
            obj = {
                "telegram": self.tg, "tmdb": self.tmdb,
                "emby": self.emby, "app": self.app,
            }[section]
            for k, v in raw.items():
                if hasattr(obj, k) and v is not None:
                    setattr(obj, k, v)

    def as_dict(self, *, redact: bool = True) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name, obj in (
            ("telegram", self.tg), ("tmdb", self.tmdb),
            ("emby", self.emby), ("app", self.app),
        ):
            d = {}
            for k in self.UI_EDITABLE.get(name, []):
                v = getattr(obj, k)
                d[k] = "******" if (redact and k in self.SECRET_FIELDS and v) else v
            out[name] = d
        return out


def load_config(config_path: Path | None = None) -> Config:
    """加载配置：先读 config.yaml 打底，再用 env 覆盖（env 优先级更高）。"""
    cfg = Config()
    if config_path is None:
        config_path = Path("config/config.yaml")
    if config_path.exists() and yaml is not None:
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            cfg._apply_yaml(data)
        except Exception:
            pass
    cfg._apply_env()
    return cfg
