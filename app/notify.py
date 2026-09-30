"""推送层：统一 Message 结构 + 多渠道抽象（对齐 MoviePilot）。

Message 是唯一的消息载体，各渠道（Telegram / 后续的微信等）实现
各自的 deliver()。当前只实现 Telegram（海报图 + caption 文字），
渠道接口已预留扩展点。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

import httpx

from .config import TelegramSettings
from .log import log


@dataclass
class Message:
    """统一消息结构（对齐 MoviePilot 的 _SchemaMessage）。"""

    title: str = ""
    text: str = ""
    image: str = ""              # 海报图片 URL
    link: str = ""               # 详情链接
    image_caption: str = ""      # 图片下方的 caption 文字

    @property
    def caption(self) -> str:
        """图片 caption：优先 image_caption，其次 text，最后 title。"""
        return self.image_caption or self.text or self.title


class Channel(abc.ABC):
    """推送渠道抽象基类。"""

    @abc.abstractmethod
    async def deliver(self, msg: Message) -> bool:
        """投递一条消息，成功返回 True。"""


class TelegramChannel(Channel):
    def __init__(self, settings: TelegramSettings):
        self.settings = settings

    def _client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {"timeout": 20.0}
        if self.settings.proxy:
            kwargs["proxy"] = self.settings.proxy
        return httpx.AsyncClient(**kwargs)

    def _base(self) -> str:
        return (self.settings.api_base or "https://api.telegram.org").rstrip("/")

    def _endpoint(self, method: str) -> str:
        return f"{self._base()}/bot{self.settings.bot_token}/{method}"

    def _chat_payload(self) -> dict[str, Any]:
        p: dict[str, Any] = {"chat_id": self.settings.chat_id}
        if self.settings.thread_id:
            p["message_thread_id"] = self.settings.thread_id
        return p

    async def _download(self, url: str) -> bytes | None:
        async with self._client() as c:
            r = await c.get(url)
            return r.content if r.status_code == 200 else None

    async def deliver(self, msg: Message) -> bool:
        if not self.settings.enabled:
            log.debug("Telegram 未配置，跳过推送")
            return False
        payload = self._chat_payload()
        try:
            if msg.image:
                data = await self._download(msg.image)
                if data:
                    caption = msg.caption
                    if msg.link:
                        caption += f"\n{msg.link}"
                    payload["caption"] = caption
                    files = {"photo": ("poster.jpg", data)}
                    async with self._client() as c:
                        r = await c.post(self._endpoint("sendPhoto"), data=payload, files=files)
                        r.raise_for_status()
                    return True
            # 退化为纯文字
            text = msg.text or msg.title
            if msg.link:
                text += f"\n{msg.link}"
            payload["text"] = text
            async with self._client() as c:
                r = await c.post(self._endpoint("sendMessage"), json=payload)
                r.raise_for_status()
            return True
        except Exception as e:
            log.warning("Telegram 推送失败：%s", e)
            # 最后尝试纯文字兜底
            try:
                payload["text"] = msg.text or msg.title
                async with self._client() as c:
                    r = await c.post(self._endpoint("sendMessage"), json=payload)
                    r.raise_for_status()
                return True
            except Exception as e2:
                log.error("Telegram 文字兜底也失败：%s", e2)
                return False


class Notifier:
    """多渠道分发器。"""

    def __init__(self, channels: list[Channel] | None = None):
        self.channels = channels or []

    async def push(self, msg: Message) -> bool:
        """投递到所有渠道，任一成功即返回 True。"""
        if not self.channels:
            return False
        results = []
        for ch in self.channels:
            try:
                results.append(await ch.deliver(msg))
            except Exception as e:
                log.warning("渠道 %s 投递异常：%s", type(ch).__name__, e)
                results.append(False)
        return any(results)
